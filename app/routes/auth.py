"""
Blueprint de Autenticación:
  GET  /           → landing page
  GET/POST /login  → iniciar sesión
  GET/POST /registro → registro solo aprendices
  GET  /logout     → cerrar sesión
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, session, make_response
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from app import db
from app.models.usuario import Usuario
from app.models.rol import Rol
from app.models.usuario_rol import UsuarioRol
from app.models.aprendiz import Aprendiz
from app.models.curso import Curso
from app.models.curso_aprendiz import CursoAprendiz
from app.utils import (get_user_role, HORAS_PRACTICA_POR_DEFECTO,
                       avisar_admins_ficha_pendiente)

bp = Blueprint('auth', __name__)

LONGITUD_MINIMA_PASSWORD = 6

# Perfil elegido en el formulario -> nombre del rol en la base de datos.
# El acceso solo se concede si la cuenta tiene ese rol.
PERFILES = {
    'aprendiz':   'aprendiz',
    'instructor': 'instructor',
    'admin':      'superusuario',
}
ETIQUETA_PERFIL = {
    'aprendiz':   'Aprendiz',
    'instructor': 'Instructor',
    'admin':      'Administrador',
}


# ─── Landing page ─────────────────────────────
@bp.route('/')
def landing():
    if current_user.is_authenticated:
        return _redirect_by_role(current_user)
    return render_template('auth/landing.html')


# ─── Login ────────────────────────────────────
@bp.route('/login', methods=['GET', 'POST'])
def login():
    # Eliminado para permitir ver el formulario de login en nuevas pestañas
    # if current_user.is_authenticated:
    #     return _redirect_by_role(current_user)

    if request.method == 'POST':
        correo   = request.form.get('correo', '').strip().lower()
        password = request.form.get('password', '')

        if not correo or not password:
            flash('Ingresa tu correo y contraseña.', 'danger')
            return render_template('auth/login.html')

        usuario = Usuario.query.filter_by(correo=correo).first()

        # Mensaje genérico: no revelamos si el correo existe o no,
        # para no facilitar el descubrimiento de cuentas.
        if not usuario or not check_password_hash(usuario.password_hash, password):
            flash('Correo o contraseña incorrectos.', 'danger')
            return render_template('auth/login.html')

        if not usuario.estado:
            flash('Tu cuenta está desactivada. Contacta al administrador.', 'warning')
            return render_template('auth/login.html')

        # El perfil elegido debe corresponder a un rol de la cuenta.
        perfil = request.form.get('perfil', '').strip().lower()
        if perfil not in PERFILES:
            flash('Selecciona el tipo de cuenta con el que quieres ingresar.', 'danger')
            return render_template('auth/login.html')

        rol_requerido = PERFILES[perfil]
        roles_usuario = {ur.rol.nombre.lower() for ur in usuario.roles}
        if rol_requerido not in roles_usuario:
            propios = [ETIQUETA_PERFIL[p] for p, r in PERFILES.items() if r in roles_usuario]
            if propios:
                flash(f'Esta cuenta no es de tipo {ETIQUETA_PERFIL[perfil]}. '
                      f'Ingresa como {" o ".join(propios)}.', 'danger')
            else:
                flash('Tu cuenta no tiene un rol asignado. Contacta al administrador.',
                      'danger')
            return render_template('auth/login.html', perfil=perfil)

        session.permanent = True
        login_user(usuario, remember=False)
        flash(f'¡Bienvenido, {usuario.nombres}!', 'success')

        return _redirect_by_perfil(perfil, login_success=True)

    return render_template('auth/login.html')


# ─── Registro (solo aprendices) ───────────────
@bp.route('/registro', methods=['GET', 'POST'])
def registro():
    # Eliminado para permitir el registro incluso si hay sesión
    # if current_user.is_authenticated:
    #     return _redirect_by_role(current_user)

    if request.method == 'POST':
        datos = {
            'tipo_documento':   request.form.get('tipo_documento', '').strip(),
            'numero_documento': request.form.get('numero_documento', '').strip(),
            'nombres':          request.form.get('nombres', '').strip(),
            'apellidos':        request.form.get('apellidos', '').strip(),
            'correo':           request.form.get('correo', '').strip().lower(),
            'telefono':         request.form.get('telefono', '').strip(),
            'password':         request.form.get('password', ''),
            'confirm_password': request.form.get('confirm_password', ''),
            'codigo_ficha':     request.form.get('codigo_ficha', '').strip(),
        }

        # Validaciones básicas
        if not all([datos['nombres'], datos['apellidos'], datos['correo'], datos['password'], datos['codigo_ficha']]):
            flash('Completa todos los campos obligatorios.', 'danger')
            return render_template('auth/registro.html')

        if datos['password'] != datos['confirm_password']:
            flash('Las contraseñas no coinciden.', 'danger')
            return render_template('auth/registro.html')

        if len(datos['password']) < LONGITUD_MINIMA_PASSWORD:
            flash(f"La contraseña debe tener al menos {LONGITUD_MINIMA_PASSWORD} caracteres.",
                  'danger')
            return render_template('auth/registro.html')

        if '@' not in datos['correo'] or '.' not in datos['correo'].split('@')[-1]:
            flash('Ingresa un correo electrónico válido.', 'danger')
            return render_template('auth/registro.html')

        if Usuario.query.filter_by(correo=datos['correo']).first():
            flash('Ya existe una cuenta con ese correo.', 'warning')
            return render_template('auth/registro.html')
            
        # Si la ficha todavía no existe como curso, el registro NO se rechaza:
        # el aprendiz queda en espera y se avisa a los administradores para que
        # la creen. Al crearla, se matricula solo (ver utils.matricular_pendientes).
        curso_asignar = Curso.query.filter_by(ficha=datos['codigo_ficha']).first()

        # Crear usuario
        nuevo_usuario = Usuario(
            tipo_documento=datos['tipo_documento'],
            numero_documento=datos['numero_documento'],
            nombres=datos['nombres'],
            apellidos=datos['apellidos'],
            correo=datos['correo'],
            telefono=datos['telefono'],
            password_hash=generate_password_hash(datos['password']),
            estado=True
        )
        db.session.add(nuevo_usuario)
        db.session.flush()  # obtener id_usuario sin commit

        # Asignar rol aprendiz
        rol_aprendiz = Rol.query.filter_by(nombre='aprendiz').first()
        if rol_aprendiz:
            db.session.add(UsuarioRol(id_usuario=nuevo_usuario.id_usuario, id_rol=rol_aprendiz.id_rol))

        # Crear registro en tabla aprendiz
        aprendiz = Aprendiz(
            id_usuario=nuevo_usuario.id_usuario,
            ficha=datos['codigo_ficha'],
            estado_practica='En proceso',
            horas_requeridas=HORAS_PRACTICA_POR_DEFECTO,
            horas_cumplidas=0
        )
        db.session.add(aprendiz)
        db.session.flush()

        if curso_asignar:
            db.session.add(CursoAprendiz(id_curso=curso_asignar.id_curso,
                                         id_aprendiz=aprendiz.id_aprendiz))
        else:
            avisar_admins_ficha_pendiente(datos['codigo_ficha'], nuevo_usuario)

        db.session.commit()

        if curso_asignar:
            flash('Cuenta creada correctamente. Inicia sesión.', 'success')
        else:
            flash(f"Cuenta creada. La ficha {datos['codigo_ficha']} todavía no está "
                  "registrada: un administrador la creará y quedarás matriculado "
                  "automáticamente. Ya puedes iniciar sesión.", 'info')
        return redirect(url_for('auth.login'))

    return render_template('auth/registro.html')


# ─── Logout ───────────────────────────────────
@bp.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    flash('Sesión cerrada.', 'info')
    return redirect(url_for('auth.landing'))


# ─── Helper: redirigir al panel del perfil elegido ──
def _redirect_by_perfil(perfil, login_success=False):
    kwargs = {'login_success': '1'} if login_success else {}
    if perfil == 'admin':
        return redirect(url_for('admin.dashboard', **kwargs))
    if perfil == 'instructor':
        return redirect(url_for('instructor.dashboard', **kwargs))
    return redirect(url_for('aprendiz.dashboard', **kwargs))


# ─── Helper: redirigir según rol ──────────────
def _redirect_by_role(usuario, login_success=False):
    rol = get_user_role(usuario)
    kwargs = {'login_success': '1'} if login_success else {}
    if rol == 'superusuario':
        return redirect(url_for('admin.dashboard', **kwargs))
    if rol == 'instructor':
        return redirect(url_for('instructor.dashboard', **kwargs))
    return redirect(url_for('aprendiz.dashboard', **kwargs))


# ─── Páginas legales (públicas) ───────────────
@bp.route('/privacidad')
def privacidad():
    """Política de privacidad. Debe ser accesible sin iniciar sesión:
    Google la exige para publicar la aplicación y para verificarla."""
    from flask import current_app
    return render_template(
        'auth/legal.html',
        documento='privacidad',
        contacto=current_app.config.get('CONTACTO_EMAIL'),
        entidad=current_app.config.get('ENTIDAD_RESPONSABLE'),
    )


@bp.route('/terminos')
def terminos():
    """Términos de uso. También pública, por el mismo motivo."""
    from flask import current_app
    return render_template(
        'auth/legal.html',
        documento='terminos',
        contacto=current_app.config.get('CONTACTO_EMAIL'),
        entidad=current_app.config.get('ENTIDAD_RESPONSABLE'),
    )
