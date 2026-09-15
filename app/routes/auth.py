"""
Blueprint de Autenticación:
  GET  /           → landing page
  GET/POST /login  → iniciar sesión
  GET/POST /registro → registro solo aprendices (queda pendiente de confirmar)
  GET  /registro/revisa-tu-correo → aviso tras enviar la confirmación
  GET  /verificar/<token> → confirma el correo y crea la cuenta
  GET  /logout     → cerrar sesión
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, session, make_response
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from app import db
from app.models.usuario import Usuario
from app.servicios import verificacion
from app.utils import get_user_role, HORAS_PRACTICA_POR_DEFECTO

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
    """La portada ya no es una página aparte: el propio acceso hace de portada.

    Se conserva la ruta porque hay enlaces que apuntan aquí (marca, páginas de
    error); simplemente redirige.
    """
    if current_user.is_authenticated:
        return _redirect_by_role(current_user)
    return redirect(url_for('auth.login'))


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
    """Registro de aprendices. La cuenta no se crea aquí: queda pendiente de
    que la persona confirme su correo desde el enlace que recibe."""
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

        def _error(mensaje, categoria='danger'):
            flash(mensaje, categoria)
            return render_template('auth/registro.html')

        # ── Validaciones ──────────────────────────
        if not all([datos['nombres'], datos['apellidos'], datos['correo'],
                    datos['password'], datos['codigo_ficha']]):
            return _error('Completa todos los campos obligatorios.')

        if datos['password'] != datos['confirm_password']:
            return _error('Las contraseñas no coinciden.')

        if len(datos['password']) < LONGITUD_MINIMA_PASSWORD:
            return _error(f'La contraseña debe tener al menos '
                          f'{LONGITUD_MINIMA_PASSWORD} caracteres.')

        if '@' not in datos['correo'] or '.' not in datos['correo'].split('@')[-1]:
            return _error('Ingresa un correo electrónico válido.')

        if Usuario.query.filter_by(correo=datos['correo']).first():
            return _error('Ya existe una cuenta con ese correo.', 'warning')

        if datos['numero_documento'] and Usuario.query.filter_by(
                numero_documento=datos['numero_documento']).first():
            return _error('Ya existe una cuenta con ese número de documento.',
                          'warning')

        # ── Alta en espera ────────────────────────
        # No se crea el usuario todavía: si el correo tuviera una errata,
        # quedaría una cuenta inservible ocupando esa dirección y ese documento.
        pendiente = verificacion.crear_pendiente(
            correo=datos['correo'],
            datos={
                'tipo_documento':   datos['tipo_documento'],
                'numero_documento': datos['numero_documento'],
                'nombres':          datos['nombres'],
                'apellidos':        datos['apellidos'],
                'telefono':         datos['telefono'],
                'password_hash':    generate_password_hash(datos['password']),
                'rol':              'aprendiz',
                'codigo_ficha':     datos['codigo_ficha'],
                'estado_practica':  'En proceso',
                'horas_requeridas': HORAS_PRACTICA_POR_DEFECTO,
            },
            origen='registro')

        if not verificacion.enviar(pendiente, nombre=datos['nombres']):
            # Sin correo enviado no hay forma de confirmar: se retira la
            # solicitud para que pueda reintentarlo con los mismos datos.
            db.session.delete(pendiente)
            db.session.commit()
            return _error('No pudimos enviar el correo de confirmación en este '
                          'momento. Inténtalo de nuevo en unos minutos o avisa '
                          'a un administrador.')

        session['correo_por_verificar'] = datos['correo']
        return redirect(url_for('auth.revisa_tu_correo'))

    return render_template('auth/registro.html')


# ─── Aviso: revisa tu correo ──────────────────
@bp.route('/registro/revisa-tu-correo')
def revisa_tu_correo():
    correo = session.get('correo_por_verificar')
    if not correo:
        return redirect(url_for('auth.registro'))
    return render_template('auth/revisa_correo.html', correo=correo,
                           horas=verificacion.HORAS_VALIDEZ)


# ─── Confirmación del correo ──────────────────
@bp.route('/verificar/<token>')
def verificar_correo(token):
    """El enlace del correo. Aquí es donde la cuenta pasa a existir."""
    try:
        pendiente = verificacion.leer_token(token)
        usuario, ficha_en_espera = verificacion.confirmar(pendiente)
    except verificacion.ErrorVerificacion as e:
        flash(str(e), 'warning')
        return redirect(url_for('auth.login'))

    session.pop('correo_por_verificar', None)
    flash(f'Correo confirmado. Tu cuenta ya está activa, {usuario.nombres}: '
          'inicia sesión.', 'success')
    if ficha_en_espera:
        flash(f'La ficha {ficha_en_espera} todavía no está registrada. Un '
              'administrador la creará y quedarás matriculado automáticamente.',
              'info')
    return redirect(url_for('auth.login'))


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
