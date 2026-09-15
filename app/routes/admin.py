"""
Blueprint Admin/Superusuario:
  /admin/dashboard
  /admin/usuarios
  /admin/roles
  /admin/instructores
  /admin/empresas
  /admin/historial
  /admin/backup
  /admin/fichas
"""
import io
import os
from datetime import datetime

from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, send_file)
from flask_login import current_user, login_required
from werkzeug.security import generate_password_hash

from app import db
from app.models.aprendiz import Aprendiz
from app.models.curso import Curso
from app.models.curso_aprendiz import CursoAprendiz
from app.models.curso_instructor import CursoInstructor
from app.models.empresa import Empresa
from app.models.evidencia import Evidencia
from app.models.historial_cambios import HistorialCambios
from app.models.instructor import Instructor
from app.models.rol import Rol
from app.models.usuario import Usuario
from app.models.usuario_rol import UsuarioRol
from app.models.notificacion import Notificacion
from app.models.progreso_aprendiz import ProgresoAprendiz
from app.models.aprendiz_backup import AprendizBackup
from app.models.verificacion_correo import VerificacionCorreo
from app.servicios import verificacion
from app.utils import (role_required, log_historial, calcular_progreso,
                       directorio_evidencias, fichas_pendientes,
                       matricular_pendientes, resumen_curso,
                       avisar_admins_ficha_pendiente,
                       HORAS_PRACTICA_POR_DEFECTO, TIPOS_DOCUMENTO,
                       ESTADOS_PRACTICA)

bp = Blueprint('admin', __name__, url_prefix='/admin')

LONGITUD_MINIMA_PASSWORD = 6


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _parse_fecha(valor):
    return datetime.strptime(valor, '%Y-%m-%d').date() if valor else None


def _volver_ficha(id_curso):
    """Tras asignar o quitar un instructor, volver de donde se venía."""
    if request.form.get('volver') == 'detalle':
        return redirect(url_for('admin.ficha_detalle', id_curso=id_curso))
    return redirect(url_for('admin.fichas'))


def _destino(por_defecto='admin.usuarios'):
    """A qué listado volver tras guardar.

    El formulario elige entre una lista cerrada de endpoints: así la misma
    acción sirve desde varias pantallas sin aceptar URLs de fuera."""
    permitidos = {'usuarios': 'admin.usuarios', 'instructores': 'admin.instructores'}
    return redirect(url_for(permitidos.get(request.form.get('volver', ''), por_defecto)))



def _id_rol_superusuario():
    rol = Rol.query.filter_by(nombre='superusuario').first()
    return rol.id_rol if rol else None


def _total_superusuarios_activos():
    id_rol = _id_rol_superusuario()
    if not id_rol:
        return 0
    return (db.session.query(Usuario)
            .join(UsuarioRol, UsuarioRol.id_usuario == Usuario.id_usuario)
            .filter(UsuarioRol.id_rol == id_rol, Usuario.estado.is_(True))
            .count())


def _es_superusuario(id_usuario):
    id_rol = _id_rol_superusuario()
    if not id_rol:
        return False
    return UsuarioRol.query.filter_by(id_usuario=id_usuario, id_rol=id_rol).first() is not None


def _resumen_borrado(usuarios):
    """Qué se llevaría por delante el borrado de cada usuario.

    Se calcula en consultas agrupadas (no una por usuario) para poder mostrarlo
    en la confirmación sin penalizar el listado.
    """
    ids = [u.id_usuario for u in usuarios]
    resumen = {i: {'evidencias': 0, 'fichas': 0, 'notificaciones': 0, 'historial': 0}
               for i in ids}
    if not ids:
        return resumen

    def _contar(consulta, clave):
        for id_usuario, total in consulta:
            if id_usuario in resumen:
                resumen[id_usuario][clave] = int(total)

    _contar(db.session.query(Notificacion.id_usuario, db.func.count())
            .filter(Notificacion.id_usuario.in_(ids))
            .group_by(Notificacion.id_usuario).all(), 'notificaciones')

    _contar(db.session.query(HistorialCambios.id_usuario, db.func.count())
            .filter(HistorialCambios.id_usuario.in_(ids))
            .group_by(HistorialCambios.id_usuario).all(), 'historial')

    # Evidencias y fichas del aprendiz
    _contar(db.session.query(Aprendiz.id_usuario, db.func.count(Evidencia.id_evidencia))
            .join(Evidencia, Evidencia.id_aprendiz == Aprendiz.id_aprendiz)
            .filter(Aprendiz.id_usuario.in_(ids))
            .group_by(Aprendiz.id_usuario).all(), 'evidencias')

    _contar(db.session.query(Aprendiz.id_usuario, db.func.count())
            .join(CursoAprendiz, CursoAprendiz.id_aprendiz == Aprendiz.id_aprendiz)
            .filter(Aprendiz.id_usuario.in_(ids))
            .group_by(Aprendiz.id_usuario).all(), 'fichas')

    # Fichas a cargo del instructor (se suman a la misma casilla)
    for id_usuario, total in (db.session.query(Instructor.id_usuario, db.func.count())
                              .join(CursoInstructor,
                                    CursoInstructor.id_instructor == Instructor.id_instructor)
                              .filter(Instructor.id_usuario.in_(ids))
                              .group_by(Instructor.id_usuario).all()):
        if id_usuario in resumen:
            resumen[id_usuario]['fichas'] += int(total)

    return resumen


# ─── Dashboard ────────────────────────────────
@bp.route('/dashboard')
@login_required
@role_required('superusuario')
def dashboard():
    total_usuarios     = Usuario.query.count()
    total_aprendices   = Aprendiz.query.count()
    total_instructores = Instructor.query.count()
    total_empresas     = Empresa.query.filter_by(activa=True).count()
    cambios_recientes  = (HistorialCambios.query
                          .order_by(HistorialCambios.fecha.desc())
                          .limit(8).all())

    # Tarjetas de ficha, con su estado y cuántos aprendices e instructores tiene
    cursos = Curso.query.order_by(Curso.nombre).all()
    conteos = dict(
        db.session.query(CursoAprendiz.id_curso, db.func.count(CursoAprendiz.id_aprendiz))
        .group_by(CursoAprendiz.id_curso).all())
    fichas_data = []
    for curso in cursos:
        fila = {
            'curso': curso,
            'aprendices_count': int(conteos.get(curso.id_curso, 0)),
            'instructores': [ci.instructor for ci in curso.instructores if ci.instructor],
        }
        fila.update(resumen_curso(curso))
        fichas_data.append(fila)

    pendientes = fichas_pendientes()
    return render_template('admin/dashboard.html',
                           total_usuarios=total_usuarios,
                           total_fichas=len(cursos),
                           total_aprendices=total_aprendices,
                           total_instructores=total_instructores,
                           total_empresas=total_empresas,
                           fichas_data=fichas_data,
                           pendientes=pendientes,
                           aprendices_en_espera=sum(len(p['aprendices']) for p in pendientes),
                           cursos_en_marcha=sum(1 for f in fichas_data
                                                if f['estado'] == 'en_curso'),
                           cambios_recientes=cambios_recientes)


# ─── Gestionar Usuarios ───────────────────────
@bp.route('/usuarios')
@login_required
@role_required('superusuario')
def usuarios():
    q = request.args.get('q', '').strip()
    query = Usuario.query
    if q:
        query = query.filter(
            (Usuario.nombres.ilike(f'%{q}%')) |
            (Usuario.apellidos.ilike(f'%{q}%')) |
            (Usuario.correo.ilike(f'%{q}%'))
        )
    lista = query.order_by(Usuario.fecha_creacion.desc()).all()
    roles = Rol.query.all()

    # Altas que esperan confirmación. Se aprovecha para retirar las caducadas:
    # no hace falta una tarea programada para algo que se consulta a diario.
    verificacion.limpiar_caducadas()
    pendientes = []
    for p in (VerificacionCorreo.query
              .order_by(VerificacionCorreo.fecha_creacion.desc()).all()):
        d = verificacion.datos_de(p)
        pendientes.append({
            'registro': p,
            'nombre': f"{d.get('nombres', '')} {d.get('apellidos', '')}".strip(),
            'rol': d.get('rol'),
            'ficha': d.get('codigo_ficha'),
        })

    return render_template('admin/usuarios.html', usuarios=lista, roles=roles, q=q,
                           pendientes=pendientes,
                           resumen=_resumen_borrado(lista),
                           tipos_documento=TIPOS_DOCUMENTO,
                           estados_practica=ESTADOS_PRACTICA,
                           horas_por_defecto=HORAS_PRACTICA_POR_DEFECTO,
                           cursos=Curso.query.order_by(Curso.nombre).all())


@bp.route('/usuarios/crear', methods=['POST'])
@login_required
@role_required('superusuario')
def crear_usuario():
    nombres   = request.form.get('nombres', '').strip()
    apellidos = request.form.get('apellidos', '').strip()
    correo    = request.form.get('correo', '').strip().lower()
    password  = request.form.get('password', '')
    id_rol    = request.form.get('id_rol', type=int)

    # Datos personales: los mismos que pide el registro público, para que un
    # usuario creado por el admin no nazca incompleto.
    tipo_documento   = request.form.get('tipo_documento', '').strip()
    numero_documento = request.form.get('numero_documento', '').strip()
    telefono         = request.form.get('telefono', '').strip()

    if not nombres or not apellidos or not correo:
        flash('Nombres, apellidos y correo son obligatorios.', 'danger')
        return redirect(url_for('admin.usuarios'))

    if '@' not in correo or '.' not in correo.split('@')[-1]:
        flash('Ingresa un correo electrónico válido.', 'danger')
        return redirect(url_for('admin.usuarios'))

    if len(password) < LONGITUD_MINIMA_PASSWORD:
        flash(f'La contraseña debe tener al menos {LONGITUD_MINIMA_PASSWORD} caracteres.',
              'danger')
        return redirect(url_for('admin.usuarios'))

    if tipo_documento and tipo_documento not in dict(TIPOS_DOCUMENTO):
        flash('Tipo de documento inválido.', 'danger')
        return redirect(url_for('admin.usuarios'))

    if Usuario.query.filter_by(correo=correo).first():
        flash('Ya existe un usuario con ese correo.', 'warning')
        return redirect(url_for('admin.usuarios'))

    if numero_documento and Usuario.query.filter_by(
            numero_documento=numero_documento).first():
        flash('Ya existe un usuario con ese número de documento.', 'warning')
        return redirect(url_for('admin.usuarios'))

    rol = db.session.get(Rol, id_rol) if id_rol else None
    if id_rol and not rol:
        flash('El rol seleccionado no existe.', 'danger')
        return redirect(url_for('admin.usuarios'))

    nombre_rol = rol.nombre if rol else None

    # ── Campos que solo aplican a un rol ───────────────────
    codigo_ficha = estado_practica = ''
    horas_requeridas = HORAS_PRACTICA_POR_DEFECTO
    inicio = fin = None
    area_formacion = ''

    if nombre_rol == 'aprendiz':
        codigo_ficha    = request.form.get('codigo_ficha', '').strip()
        estado_practica = request.form.get('estado_practica', '').strip() or 'En proceso'

        if not codigo_ficha:
            flash('Indica el código de ficha del aprendiz.', 'danger')
            return redirect(url_for('admin.usuarios'))

        if estado_practica not in ESTADOS_PRACTICA:
            flash('Estado de práctica inválido.', 'danger')
            return redirect(url_for('admin.usuarios'))

        horas = request.form.get('horas_requeridas', type=int)
        if horas is not None:
            if horas < 0:
                flash('Las horas requeridas no pueden ser negativas.', 'danger')
                return redirect(url_for('admin.usuarios'))
            horas_requeridas = horas

        try:
            inicio = _parse_fecha(request.form.get('fecha_inicio_practica', '').strip())
            fin = _parse_fecha(request.form.get('fecha_fin_practica', '').strip())
        except ValueError:
            flash('Formato de fecha inválido.', 'danger')
            return redirect(url_for('admin.usuarios'))

        if inicio and fin and fin <= inicio:
            flash('La fecha de finalización debe ser posterior a la de inicio.', 'danger')
            return redirect(url_for('admin.usuarios'))

    elif nombre_rol == 'instructor':
        area_formacion = request.form.get('area_formacion', '').strip()

    # La cuenta no se crea aquí: se le pide a la persona que confirme su
    # correo. Si la dirección tuviera una errata, el usuario quedaría creado
    # pero incomunicado, ocupando ese correo y ese documento.
    pendiente = verificacion.crear_pendiente(
        correo=correo,
        datos={
            'tipo_documento':   tipo_documento,
            'numero_documento': numero_documento,
            'nombres':          nombres,
            'apellidos':        apellidos,
            'telefono':         telefono,
            'password_hash':    generate_password_hash(password),
            'rol':              nombre_rol,
            'codigo_ficha':     codigo_ficha,
            'estado_practica':  estado_practica or 'En proceso',
            'horas_requeridas': horas_requeridas,
            'fecha_inicio_practica': inicio.isoformat() if inicio else None,
            'fecha_fin_practica':    fin.isoformat() if fin else None,
            'area_formacion':   area_formacion,
        },
        origen='admin',
        id_creador=current_user.id_usuario)

    quien = f'{current_user.nombres} {current_user.apellidos}'.strip()
    if not verificacion.enviar(pendiente, nombre=nombres, quien_invita=quien):
        db.session.delete(pendiente)
        db.session.commit()
        flash('No se pudo enviar el correo de confirmación, así que no se creó '
              'nada. Revisa la dirección y vuelve a intentarlo.', 'danger')
        return redirect(url_for('admin.usuarios'))

    log_historial(current_user, 'Usuarios', 'CREAR',
                  f'Invitación enviada a {correo} (pendiente de confirmar)')
    db.session.commit()

    flash(f'Le enviamos un correo de confirmación a {correo}. La cuenta se crea '
          'cuando abra el enlace.', 'success')
    return redirect(url_for('admin.usuarios'))


@bp.route('/usuarios/pendientes/<int:id_verificacion>/reenviar', methods=['POST'])
@login_required
@role_required('superusuario')
def reenviar_verificacion(id_verificacion):
    pendiente = VerificacionCorreo.query.get_or_404(id_verificacion)
    datos = verificacion.datos_de(pendiente)
    quien = f'{current_user.nombres} {current_user.apellidos}'.strip()

    if verificacion.enviar(pendiente, nombre=datos.get('nombres'), quien_invita=quien):
        flash(f'Correo de confirmación reenviado a {pendiente.correo}.', 'success')
    else:
        flash('No se pudo enviar el correo. Inténtalo de nuevo en unos minutos.',
              'danger')
    return redirect(url_for('admin.usuarios'))


@bp.route('/usuarios/pendientes/<int:id_verificacion>/cancelar', methods=['POST'])
@login_required
@role_required('superusuario')
def cancelar_verificacion(id_verificacion):
    pendiente = VerificacionCorreo.query.get_or_404(id_verificacion)
    correo = pendiente.correo
    db.session.delete(pendiente)
    log_historial(current_user, 'Usuarios', 'ELIMINAR',
                  f'Invitación cancelada: {correo}')
    db.session.commit()
    flash(f'Invitación a {correo} cancelada. El enlace que se envió ya no sirve.',
          'info')
    return redirect(url_for('admin.usuarios'))


@bp.route('/usuarios/<int:id_usuario>/editar', methods=['POST'])
@login_required
@role_required('superusuario')
def editar_usuario(id_usuario):
    u = Usuario.query.get_or_404(id_usuario)
    nombres   = request.form.get('nombres', '').strip()
    apellidos = request.form.get('apellidos', '').strip()
    correo    = request.form.get('correo', '').strip().lower()
    telefono  = request.form.get('telefono', '').strip()
    password  = request.form.get('password', '')
    tipo_documento   = request.form.get('tipo_documento', '').strip()
    numero_documento = request.form.get('numero_documento', '').strip()

    if not nombres or not apellidos or not correo:
        flash('Nombres, apellidos y correo son obligatorios.', 'danger')
        return _destino()

    if correo != u.correo and Usuario.query.filter_by(correo=correo).first():
        flash('Ya existe otro usuario con ese correo.', 'warning')
        return _destino()

    if tipo_documento and tipo_documento not in dict(TIPOS_DOCUMENTO):
        flash('Tipo de documento inválido.', 'danger')
        return _destino()

    if numero_documento and numero_documento != u.numero_documento and Usuario.query.filter_by(
            numero_documento=numero_documento).first():
        flash('Ya existe otro usuario con ese número de documento.', 'warning')
        return _destino()

    if password and len(password) < LONGITUD_MINIMA_PASSWORD:
        flash(f'La contraseña debe tener al menos {LONGITUD_MINIMA_PASSWORD} caracteres.',
              'danger')
        return _destino()

    u.nombres = nombres
    u.apellidos = apellidos
    u.correo = correo
    u.telefono = telefono
    u.tipo_documento = tipo_documento or None
    u.numero_documento = numero_documento or None

    if password:
        u.password_hash = generate_password_hash(password)

    log_historial(current_user, 'Usuarios', 'MODIFICAR', f'Usuario {correo} editado')
    db.session.commit()
    flash(f'Usuario {nombres} {apellidos} actualizado.', 'success')
    return _destino()


@bp.route('/usuarios/<int:id_usuario>/toggle', methods=['POST'])
@login_required
@role_required('superusuario')
def toggle_usuario(id_usuario):
    u = Usuario.query.get_or_404(id_usuario)

    if u.id_usuario == current_user.id_usuario:
        flash('No puedes desactivar tu propia cuenta.', 'warning')
        return redirect(url_for('admin.usuarios'))

    # Evita quedarse sin ningún superusuario activo (bloqueo total del sistema)
    if u.estado and _es_superusuario(u.id_usuario) and _total_superusuarios_activos() <= 1:
        flash('No puedes desactivar al único superusuario activo.', 'danger')
        return redirect(url_for('admin.usuarios'))

    u.estado = not u.estado
    estado_str = 'activado' if u.estado else 'desactivado'
    log_historial(current_user, 'Usuarios', 'MODIFICAR',
                  f'Usuario {u.correo} {estado_str}')
    db.session.commit()
    flash(f'Usuario {estado_str}.', 'success')
    return redirect(url_for('admin.usuarios'))


@bp.route('/usuarios/<int:id_usuario>/eliminar', methods=['POST'])
@login_required
@role_required('superusuario')
def eliminar_usuario(id_usuario):
    """Elimina definitivamente un usuario y todo lo que cuelga de él.

    Es irreversible. Para retirar el acceso sin perder datos está el bloqueo.
    Las entradas de auditoría NO se borran: se desligan del usuario y quedan
    como "usuario eliminado", y el borrado en sí se registra en el historial.
    """
    # Sin get_or_404: si el usuario ya no está (doble envío del formulario, o
    # la pestaña llevaba abierta desde antes), un 404 seco desconcierta. Se
    # informa y se vuelve al listado, que es lo que la persona espera ver.
    u = db.session.get(Usuario, id_usuario)
    if u is None:
        flash('Ese usuario ya no existe; es posible que se eliminara antes.', 'info')
        return redirect(url_for('admin.usuarios'))

    if u.id_usuario == current_user.id_usuario:
        flash('No puedes eliminar tu propia cuenta.', 'warning')
        return redirect(url_for('admin.usuarios'))

    if _es_superusuario(u.id_usuario) and _total_superusuarios_activos() <= 1 and u.estado:
        flash('No puedes eliminar al único superusuario activo.', 'danger')
        return redirect(url_for('admin.usuarios'))

    # La confirmación exige reescribir el correo: evita borrar la fila de al lado
    if request.form.get('confirmacion', '').strip().lower() != (u.correo or '').lower():
        flash('La confirmación no coincide con el correo del usuario.', 'danger')
        return redirect(url_for('admin.usuarios'))

    etiqueta = f'{u.nombres} {u.apellidos} <{u.correo}>'
    archivos = []

    # ── Aprendiz: evidencias, progreso, matrículas y respaldo ──
    if u.aprendiz:
        id_ap = u.aprendiz.id_aprendiz
        for ev in Evidencia.query.filter_by(id_aprendiz=id_ap).all():
            if ev.tipo == 'archivo' and ev.contenido:
                archivos.append(os.path.basename(ev.contenido))
        Evidencia.query.filter_by(id_aprendiz=id_ap).delete(synchronize_session=False)
        ProgresoAprendiz.query.filter_by(id_aprendiz=id_ap).delete(synchronize_session=False)
        CursoAprendiz.query.filter_by(id_aprendiz=id_ap).delete(synchronize_session=False)
        AprendizBackup.query.filter_by(id_aprendiz=id_ap).delete(synchronize_session=False)
        db.session.delete(u.aprendiz)

    # ── Instructor: sus asignaciones a fichas (las fichas se conservan) ──
    if u.instructor:
        CursoInstructor.query.filter_by(
            id_instructor=u.instructor.id_instructor).delete(synchronize_session=False)
        db.session.delete(u.instructor)

    # ── Comunes ──
    Notificacion.query.filter_by(id_usuario=id_usuario).delete(synchronize_session=False)
    UsuarioRol.query.filter_by(id_usuario=id_usuario).delete(synchronize_session=False)
    if u.cuenta_google:
        db.session.delete(u.cuenta_google)

    # El rastro de auditoría se conserva, desligado del usuario borrado
    HistorialCambios.query.filter_by(id_usuario=id_usuario).update(
        {'id_usuario': None}, synchronize_session=False)

    log_historial(current_user, 'Usuarios', 'ELIMINAR',
                  f'Usuario eliminado definitivamente: {etiqueta}')
    db.session.delete(u)
    db.session.commit()

    # Los archivos se borran una vez confirmada la transacción
    if archivos:
        carpeta = directorio_evidencias()
        for nombre in archivos:
            try:
                os.remove(os.path.join(carpeta, nombre))
            except OSError:
                pass

    flash(f'Usuario {etiqueta} eliminado definitivamente.', 'success')
    return redirect(url_for('admin.usuarios'))


@bp.route('/usuarios/<int:id_usuario>/ficha', methods=['POST'])
@login_required
@role_required('superusuario')
def cambiar_ficha_aprendiz(id_usuario):
    """Mueve a un aprendiz de ficha, o lo deja sin asignar.

    Mantiene sincronizadas las dos caras del dato: el código en `aprendiz.ficha`
    y la matrícula en `curso_aprendiz`. Si se desincronizan, el aprendiz aparece
    como pendiente aunque tenga curso, o al revés.
    """
    u = Usuario.query.get_or_404(id_usuario)
    if not u.aprendiz:
        flash('Ese usuario no tiene perfil de aprendiz.', 'warning')
        return redirect(url_for('admin.usuarios'))

    id_curso = request.form.get('id_curso', type=int)
    ap = u.aprendiz

    CursoAprendiz.query.filter_by(id_aprendiz=ap.id_aprendiz).delete(
        synchronize_session=False)

    if id_curso:
        curso = Curso.query.get(id_curso)
        if not curso:
            db.session.rollback()
            flash('La ficha seleccionada no existe.', 'danger')
            return redirect(url_for('admin.usuarios'))
        db.session.add(CursoAprendiz(id_curso=curso.id_curso,
                                     id_aprendiz=ap.id_aprendiz))
        ap.ficha = curso.ficha
        detalle = f'Aprendiz {u.correo} asignado a la ficha {curso.nombre}'
        aviso = f'Aprendiz movido a la ficha "{curso.nombre}".'
    else:
        ap.ficha = None
        detalle = f'Aprendiz {u.correo} retirado de su ficha'
        aviso = 'Aprendiz retirado de su ficha.'

    log_historial(current_user, 'Aprendiz', 'MODIFICAR', detalle)
    db.session.commit()
    flash(aviso, 'success')
    destino = request.form.get('next')
    if destino and destino.startswith('/') and not destino.startswith('//'):
        return redirect(destino)
    return redirect(url_for('admin.usuarios'))


@bp.route('/fichas/matricular-pendientes', methods=['POST'])
@login_required
@role_required('superusuario')
def matricular_pendientes_ficha():
    """Matricula de golpe a los aprendices que esperan una ficha que ya existe.

    Es el caso de un código correcto sin matrícula: el curso está, solo falta
    el vínculo. Crear otra ficha sería un error.
    """
    codigo = request.form.get('codigo', '').strip()
    curso = Curso.query.filter_by(ficha=codigo).first() if codigo else None
    if not curso:
        flash('No existe ninguna ficha con ese código.', 'danger')
        return redirect(url_for('admin.fichas'))

    matriculados = matricular_pendientes(curso)
    if matriculados:
        log_historial(current_user, 'Fichas', 'MODIFICAR',
                      f'{len(matriculados)} aprendices matriculados en {curso.nombre}')
        db.session.commit()
        flash(f'Se matricularon {len(matriculados)} '
              f'aprendiz{"" if len(matriculados) == 1 else "es"} en «{curso.nombre}».',
              'success')
    else:
        flash('No quedaban aprendices por matricular en esa ficha.', 'info')
    return redirect(url_for('admin.fichas'))


# ─── Asignar Roles ────────────────────────────
@bp.route('/roles')
@login_required
@role_required('superusuario')
def roles():
    usuarios = Usuario.query.order_by(Usuario.nombres).all()
    roles_disponibles = Rol.query.all()
    return render_template('admin/roles.html',
                           usuarios=usuarios,
                           roles=roles_disponibles)


@bp.route('/roles/asignar', methods=['POST'])
@login_required
@role_required('superusuario')
def asignar_rol():
    id_usuario = request.form.get('id_usuario', type=int)
    id_rol     = request.form.get('id_rol', type=int)
    if not id_usuario or not id_rol:
        flash('Datos incompletos.', 'danger')
        return redirect(url_for('admin.roles'))

    usuario = Usuario.query.get(id_usuario)
    rol = Rol.query.get(id_rol)
    if not usuario or not rol:
        flash('Usuario o rol inexistente.', 'danger')
        return redirect(url_for('admin.roles'))

    if UsuarioRol.query.filter_by(id_usuario=id_usuario, id_rol=id_rol).first():
        flash('El usuario ya tiene ese rol.', 'warning')
        return redirect(url_for('admin.roles'))

    db.session.add(UsuarioRol(id_usuario=id_usuario, id_rol=id_rol))
    # Crear perfil si no existe
    if rol.nombre == 'aprendiz' and not Aprendiz.query.filter_by(id_usuario=id_usuario).first():
        db.session.add(Aprendiz(id_usuario=id_usuario,
                                estado_practica='En proceso',
                                horas_requeridas=HORAS_PRACTICA_POR_DEFECTO,
                                horas_cumplidas=0))
    elif rol.nombre == 'instructor' and not Instructor.query.filter_by(id_usuario=id_usuario).first():
        db.session.add(Instructor(id_usuario=id_usuario, activo=True))

    log_historial(current_user, 'Roles', 'MODIFICAR',
                  f'Rol {rol.nombre} asignado a usuario {id_usuario}')
    db.session.commit()
    flash(f'Rol "{rol.nombre}" asignado.', 'success')
    return redirect(url_for('admin.roles'))


@bp.route('/roles/quitar', methods=['POST'])
@login_required
@role_required('superusuario')
def quitar_rol():
    id_usuario = request.form.get('id_usuario', type=int)
    id_rol     = request.form.get('id_rol', type=int)

    if (id_usuario == current_user.id_usuario
            and id_rol == _id_rol_superusuario()):
        flash('No puedes quitarte a ti mismo el rol de superusuario.', 'warning')
        return redirect(url_for('admin.roles'))

    if id_rol == _id_rol_superusuario() and _total_superusuarios_activos() <= 1:
        flash('No puedes quitar el rol al único superusuario del sistema.', 'danger')
        return redirect(url_for('admin.roles'))

    ur = UsuarioRol.query.filter_by(id_usuario=id_usuario, id_rol=id_rol).first()
    if ur:
        db.session.delete(ur)
        log_historial(current_user, 'Roles', 'ELIMINAR',
                      f'Rol {id_rol} quitado a usuario {id_usuario}')
        db.session.commit()
        flash('Rol removido.', 'success')
    return redirect(url_for('admin.roles'))


# ─── Gestionar Instructores ───────────────────
@bp.route('/instructores')
@login_required
@role_required('superusuario')
def instructores():
    lista = Instructor.query.join(Usuario).order_by(Usuario.nombres).all()
    cursos = Curso.query.order_by(Curso.nombre).all()

    # Cuántos aprendices tiene cada ficha (una consulta, no una por fila)
    aprendices_por_curso = dict(
        db.session.query(CursoAprendiz.id_curso, db.func.count(CursoAprendiz.id_aprendiz))
        .group_by(CursoAprendiz.id_curso).all())

    filas = []
    for inst in lista:
        asignadas = [ci.curso for ci in inst.cursos if ci.curso]
        ids_asignadas = {c.id_curso for c in asignadas}
        filas.append({
            'instructor': inst,
            'fichas': sorted(asignadas, key=lambda c: c.nombre or ''),
            'disponibles': [c for c in cursos if c.id_curso not in ids_asignadas],
            'aprendices': sum(int(aprendices_por_curso.get(c.id_curso, 0))
                              for c in asignadas),
        })

    return render_template('admin/instructores.html', filas=filas,
                           total_fichas=len(cursos),
                           tipos_documento=TIPOS_DOCUMENTO)


@bp.route('/instructores/<int:id_instructor>/toggle', methods=['POST'])
@login_required
@role_required('superusuario')
def toggle_instructor(id_instructor):
    inst = Instructor.query.get_or_404(id_instructor)
    inst.activo = not inst.activo
    log_historial(current_user, 'Instructores', 'MODIFICAR',
                  f'Instructor {id_instructor} {"activado" if inst.activo else "desactivado"}')
    db.session.commit()
    flash('Estado del instructor actualizado.', 'success')
    return redirect(url_for('admin.instructores'))


@bp.route('/instructores/<int:id_instructor>/fichas/vincular', methods=['POST'])
@login_required
@role_required('superusuario')
def vincular_ficha_instructor(id_instructor):
    """Poner al instructor a cargo de una ficha, desde su propia pantalla."""
    inst = Instructor.query.get_or_404(id_instructor)
    id_curso = request.form.get('id_curso', type=int)

    if not id_curso:
        flash('Selecciona la ficha que quieres vincular.', 'danger')
        return redirect(url_for('admin.instructores'))

    curso = Curso.query.get_or_404(id_curso)

    if CursoInstructor.query.filter_by(id_curso=id_curso,
                                       id_instructor=id_instructor).first():
        flash('Ese instructor ya estaba a cargo de esa ficha.', 'warning')
        return redirect(url_for('admin.instructores'))

    db.session.add(CursoInstructor(id_curso=id_curso, id_instructor=id_instructor))
    log_historial(current_user, 'Instructores', 'MODIFICAR',
                  f'Instructor {id_instructor} vinculado a la ficha {curso.ficha or curso.nombre}')
    db.session.commit()
    flash(f'{inst.usuario.nombres} quedó a cargo de la ficha '
          f'{curso.ficha or curso.nombre}.', 'success')
    return redirect(url_for('admin.instructores'))


@bp.route('/instructores/<int:id_instructor>/fichas/<int:id_curso>/desvincular',
          methods=['POST'])
@login_required
@role_required('superusuario')
def desvincular_ficha_instructor(id_instructor, id_curso):
    """Quitarle la ficha al instructor. Aprendices y evidencias no se tocan."""
    ci = CursoInstructor.query.filter_by(
        id_curso=id_curso, id_instructor=id_instructor).first()

    if not ci:
        flash('Ese instructor ya no estaba a cargo de esa ficha.', 'info')
        return redirect(url_for('admin.instructores'))

    curso = ci.curso
    nombre = (ci.instructor.usuario.nombres
              if ci.instructor and ci.instructor.usuario else id_instructor)
    etiqueta = (curso.ficha or curso.nombre) if curso else id_curso
    db.session.delete(ci)

    log_historial(current_user, 'Instructores', 'MODIFICAR',
                  f'Instructor {id_instructor} desvinculado de la ficha {etiqueta}')
    db.session.commit()
    flash(f'{nombre} ya no está a cargo de la ficha {etiqueta}.', 'success')
    return redirect(url_for('admin.instructores'))


@bp.route('/instructores/<int:id_instructor>/area', methods=['POST'])
@login_required
@role_required('superusuario')
def editar_area_instructor(id_instructor):
    inst = Instructor.query.get_or_404(id_instructor)
    inst.area_formacion = request.form.get('area_formacion', '').strip() or None
    log_historial(current_user, 'Instructores', 'MODIFICAR',
                  f'Área instructor {id_instructor}: {inst.area_formacion or "sin definir"}')
    db.session.commit()
    flash('Área de formación actualizada.', 'success')
    return redirect(url_for('admin.instructores'))


# ─── Gestionar Empresas ───────────────────────
@bp.route('/empresas')
@login_required
@role_required('superusuario')
def empresas():
    lista = Empresa.query.order_by(Empresa.nombre).all()
    return render_template('admin/empresas.html', empresas=lista)


@bp.route('/empresas/crear', methods=['POST'])
@login_required
@role_required('superusuario')
def crear_empresa():
    nombre = request.form.get('nombre', '').strip()
    if not nombre:
        flash('El nombre es obligatorio.', 'danger')
        return redirect(url_for('admin.empresas'))
    e = Empresa(
        nombre=nombre,
        nit=request.form.get('nit', '').strip(),
        direccion=request.form.get('direccion', '').strip(),
        telefono=request.form.get('telefono', '').strip(),
        contacto=request.form.get('contacto', '').strip(),
        persona_contacto=request.form.get('persona_contacto', '').strip(),
        activa=True
    )
    db.session.add(e)
    log_historial(current_user, 'Empresas', 'CREAR', f'Empresa {nombre} creada')
    db.session.commit()
    flash(f'Empresa "{nombre}" creada.', 'success')
    return redirect(url_for('admin.empresas'))


@bp.route('/empresas/<int:id_empresa>/editar', methods=['POST'])
@login_required
@role_required('superusuario')
def editar_empresa(id_empresa):
    e = Empresa.query.get_or_404(id_empresa)
    nombre = request.form.get('nombre', '').strip()
    if not nombre:
        flash('El nombre es obligatorio.', 'danger')
        return redirect(url_for('admin.empresas'))

    e.nombre           = nombre
    e.nit              = request.form.get('nit', e.nit or '').strip()
    e.direccion        = request.form.get('direccion', e.direccion or '').strip()
    e.telefono         = request.form.get('telefono', e.telefono or '').strip()
    e.contacto         = request.form.get('contacto', e.contacto or '').strip()
    e.persona_contacto = request.form.get('persona_contacto', e.persona_contacto or '').strip()
    e.activa           = 'activa' in request.form
    log_historial(current_user, 'Empresas', 'MODIFICAR', f'Empresa {id_empresa} editada')
    db.session.commit()
    flash('Empresa actualizada.', 'success')
    return redirect(url_for('admin.empresas'))


# ─── Historial / Auditoría ────────────────────
@bp.route('/historial')
@login_required
@role_required('superusuario')
def historial():
    page = request.args.get('page', 1, type=int)
    registros = (HistorialCambios.query
                 .order_by(HistorialCambios.fecha.desc())
                 .paginate(page=page, per_page=30, error_out=False))
    return render_template('admin/historial.html', registros=registros)


# ─── Backup y Reportes (exportar Excel) ───────
@bp.route('/backup')
@login_required
@role_required('superusuario')
def backup():
    aprendices   = Aprendiz.query.all()
    instructores = Instructor.query.all()
    empresas     = Empresa.query.all()
    return render_template('admin/backup.html',
                           aprendices=aprendices,
                           instructores=instructores,
                           empresas=empresas)


@bp.route('/backup/exportar/<string:tipo>')
@login_required
@role_required('superusuario')
def exportar_excel(tipo):
    try:
        import openpyxl
    except ImportError:
        flash('Falta la librería openpyxl en el servidor.', 'danger')
        return redirect(url_for('admin.backup'))

    wb = openpyxl.Workbook()
    ws = wb.active

    if tipo == 'aprendices':
        ws.title = 'Aprendices'
        ws.append(['ID', 'Nombres', 'Apellidos', 'Correo', 'Ficha',
                   'Estado Práctica', 'Horas Requeridas', 'Horas Cumplidas', 'Empresa'])
        for ap in Aprendiz.query.all():
            ws.append([
                ap.id_aprendiz,
                ap.usuario.nombres if ap.usuario else '',
                ap.usuario.apellidos if ap.usuario else '',
                ap.usuario.correo if ap.usuario else '',
                ap.ficha or '',
                ap.estado_practica or '',
                ap.horas_requeridas or 0,
                ap.horas_cumplidas or 0,
                ap.empresa.nombre if ap.empresa else ''
            ])
        filename = 'aprendices.xlsx'

    elif tipo == 'instructores':
        ws.title = 'Instructores'
        ws.append(['ID', 'Nombres', 'Apellidos', 'Correo', 'Área Formación', 'Activo'])
        for inst in Instructor.query.all():
            ws.append([
                inst.id_instructor,
                inst.usuario.nombres if inst.usuario else '',
                inst.usuario.apellidos if inst.usuario else '',
                inst.usuario.correo if inst.usuario else '',
                inst.area_formacion or '',
                'Sí' if inst.activo else 'No'
            ])
        filename = 'instructores.xlsx'

    elif tipo == 'empresas':
        ws.title = 'Empresas'
        ws.append(['ID', 'Nombre', 'NIT', 'Dirección', 'Teléfono', 'Contacto', 'Persona', 'Activa'])
        for e in Empresa.query.all():
            ws.append([
                e.id_empresa, e.nombre, e.nit or '',
                e.direccion or '', e.telefono or '',
                e.contacto or '', e.persona_contacto or '',
                'Sí' if e.activa else 'No'
            ])
        filename = 'empresas.xlsx'

    elif tipo == 'historial':
        ws.title = 'Historial'
        ws.append(['ID', 'Usuario', 'Módulo', 'Acción', 'Descripción', 'Fecha'])
        for h in HistorialCambios.query.order_by(HistorialCambios.fecha.desc()).all():
            ws.append([
                h.id_historial,
                f'{h.usuario.nombres} {h.usuario.apellidos}' if h.usuario else '',
                h.modulo or '',
                h.accion or '',
                h.descripcion or '',
                h.fecha.strftime('%Y-%m-%d %H:%M:%S') if h.fecha else ''
            ])
        filename = 'historial.xlsx'
    else:
        flash('Tipo de exportación no válido.', 'danger')
        return redirect(url_for('admin.backup'))

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    log_historial(current_user, 'Backup', 'CREAR', f'Exportación Excel: {tipo}')
    db.session.commit()
    return send_file(buf, download_name=filename,
                     as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ─── Gestionar Fichas ─────────────────────────
@bp.route('/fichas')
@login_required
@role_required('superusuario')
def fichas():
    """Listado completo de fichas/cursos con búsqueda y filtrado"""
    q = request.args.get('q', '').strip()

    query = Curso.query
    if q:
        query = query.filter(Curso.nombre.ilike(f'%{q}%') | Curso.ficha.ilike(f'%{q}%'))

    cursos = query.order_by(Curso.nombre).all()

    # Conteo de aprendices de todas las fichas en UNA consulta (antes: una por ficha)
    conteos = dict(
        db.session.query(CursoAprendiz.id_curso,
                         db.func.count(CursoAprendiz.id_aprendiz))
        .group_by(CursoAprendiz.id_curso).all()
    )

    fichas_data = [{
        'curso': curso,
        'instructores': [ci.instructor for ci in curso.instructores if ci.instructor],
        'aprendices_count': int(conteos.get(curso.id_curso, 0)),
    } for curso in cursos]

    instructores_disponibles = Instructor.query.filter_by(activo=True).all()

    return render_template('admin/fichas/lista.html',
                           fichas_data=fichas_data,
                           instructores=instructores_disponibles,
                           pendientes=fichas_pendientes(),
                           q=q)


@bp.route('/fichas/crear', methods=['POST'])
@login_required
@role_required('superusuario')
def crear_ficha():
    """Crear nueva ficha/curso"""
    nombre = request.form.get('nombre', '').strip()
    ficha = request.form.get('ficha', '').strip()

    if not nombre:
        flash('El nombre es requerido.', 'danger')
        return redirect(url_for('admin.fichas'))

    try:
        fecha_inicio = _parse_fecha(request.form.get('fecha_inicio', ''))
        fecha_fin = _parse_fecha(request.form.get('fecha_fin', ''))
    except ValueError:
        flash('Formato de fecha inválido.', 'danger')
        return redirect(url_for('admin.fichas'))

    if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
        flash('La fecha de fin no puede ser anterior a la de inicio.', 'danger')
        return redirect(url_for('admin.fichas'))

    if Curso.query.filter_by(nombre=nombre).first():
        flash('Ya existe una ficha con ese nombre.', 'warning')
        return redirect(url_for('admin.fichas'))

    if ficha and Curso.query.filter_by(ficha=ficha).first():
        flash('Ya existe una ficha con ese código.', 'warning')
        return redirect(url_for('admin.fichas'))

    curso = Curso(nombre=nombre, ficha=ficha or None,
                  fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
    db.session.add(curso)
    db.session.flush()

    # Los aprendices que se registraron con este código quedaban en espera
    esperando = matricular_pendientes(curso)

    log_historial(current_user, 'Fichas', 'CREAR', f'Ficha {nombre} creada')
    db.session.commit()

    if esperando:
        flash(f'Ficha creada. Se matricularon automáticamente {len(esperando)} '
              f'aprendiz{"" if len(esperando) == 1 else "es"} que la esperaban.',
              'success')
    else:
        flash('Ficha creada correctamente.', 'success')
    return redirect(url_for('admin.fichas'))


@bp.route('/fichas/<int:id_curso>/editar', methods=['POST'])
@login_required
@role_required('superusuario')
def editar_ficha(id_curso):
    """Editar ficha"""
    curso = Curso.query.get_or_404(id_curso)
    nombre = request.form.get('nombre', '').strip()
    ficha = request.form.get('ficha', '').strip()

    try:
        fecha_inicio = _parse_fecha(request.form.get('fecha_inicio', ''))
        fecha_fin = _parse_fecha(request.form.get('fecha_fin', ''))
    except ValueError:
        flash('Formato de fecha inválido.', 'danger')
        return redirect(url_for('admin.fichas'))

    if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
        flash('La fecha de fin no puede ser anterior a la de inicio.', 'danger')
        return redirect(url_for('admin.fichas'))

    if nombre and nombre != curso.nombre:
        if Curso.query.filter_by(nombre=nombre).first():
            flash('Ya existe una ficha con ese nombre.', 'warning')
            return redirect(url_for('admin.fichas'))
        curso.nombre = nombre

    if ficha and ficha != (curso.ficha or ''):
        otra = Curso.query.filter_by(ficha=ficha).first()
        if otra and otra.id_curso != curso.id_curso:
            flash('Ya existe una ficha con ese código.', 'warning')
            return redirect(url_for('admin.fichas'))

    curso.ficha = ficha or None
    curso.fecha_inicio = fecha_inicio
    curso.fecha_fin = fecha_fin

    log_historial(current_user, 'Fichas', 'MODIFICAR', f'Ficha {curso.nombre} editada')
    db.session.commit()
    flash('Ficha actualizada.', 'success')
    return redirect(url_for('admin.fichas'))


@bp.route('/fichas/<int:id_curso>/eliminar', methods=['POST'])
@login_required
@role_required('superusuario')
def eliminar_ficha(id_curso):
    """Eliminar ficha (con validación)"""
    curso = Curso.query.get_or_404(id_curso)

    if CursoAprendiz.query.filter_by(id_curso=id_curso).count() > 0:
        flash('No se puede eliminar una ficha con aprendices asignados.', 'danger')
        return redirect(url_for('admin.fichas'))

    nombre = curso.nombre
    # Limpiar filas dependientes: sin esto la BD rechaza el DELETE por llave foránea
    CursoInstructor.query.filter_by(id_curso=id_curso).delete(synchronize_session=False)
    from app.models.progreso_aprendiz import ProgresoAprendiz
    ProgresoAprendiz.query.filter_by(id_curso=id_curso).delete(synchronize_session=False)
    db.session.delete(curso)
    log_historial(current_user, 'Fichas', 'ELIMINAR', f'Ficha {nombre} eliminada')
    db.session.commit()

    flash('Ficha eliminada correctamente.', 'success')
    return redirect(url_for('admin.fichas'))


@bp.route('/fichas/<int:id_curso>/asignar-instructor', methods=['POST'])
@login_required
@role_required('superusuario')
def asignar_instructor_ficha(id_curso):
    """Asignar instructor a ficha"""
    curso = Curso.query.get_or_404(id_curso)
    id_instructor = request.form.get('id_instructor', type=int)

    if not id_instructor:
        flash('Selecciona un instructor.', 'danger')
        return _volver_ficha(id_curso)

    instructor = Instructor.query.get_or_404(id_instructor)

    if CursoInstructor.query.filter_by(id_curso=id_curso,
                                       id_instructor=id_instructor).first():
        flash('Este instructor ya está asignado a la ficha.', 'warning')
        return _volver_ficha(id_curso)

    db.session.add(CursoInstructor(id_curso=id_curso, id_instructor=id_instructor))
    log_historial(current_user, 'Fichas', 'MODIFICAR',
                  f'Instructor {instructor.usuario.nombres} asignado a {curso.nombre}')
    db.session.commit()

    flash(f'{instructor.usuario.nombres} quedó a cargo de la ficha '
          f'{curso.ficha or curso.nombre}.', 'success')
    return _volver_ficha(id_curso)


@bp.route('/fichas/<int:id_curso>/desasignar-instructor/<int:id_instructor>',
          methods=['POST'])
@login_required
@role_required('superusuario')
def desasignar_instructor_ficha(id_curso, id_instructor):
    """Remover instructor de ficha"""
    ci = CursoInstructor.query.filter_by(
        id_curso=id_curso, id_instructor=id_instructor).first_or_404()

    curso = ci.curso
    instructor = ci.instructor
    nombre_inst = instructor.usuario.nombres if instructor and instructor.usuario else id_instructor
    db.session.delete(ci)

    log_historial(current_user, 'Fichas', 'MODIFICAR',
                  f'Instructor {nombre_inst} desasignado de {curso.nombre}')
    db.session.commit()

    flash(f'{nombre_inst} ya no está a cargo de la ficha '
          f'{curso.ficha or curso.nombre}.', 'success')
    return _volver_ficha(id_curso)


@bp.route('/fichas/<int:id_curso>/detalle')
@login_required
@role_required('superusuario')
def ficha_detalle(id_curso):
    """Vista detallada de la ficha para administrador"""
    curso = Curso.query.get_or_404(id_curso)

    matriculas = CursoAprendiz.query.filter_by(id_curso=id_curso).all()
    aprendices = [ca.aprendiz for ca in matriculas if ca.aprendiz]

    # Todas las evidencias de la ficha en una sola consulta
    evidencias_por_aprendiz = {}
    if aprendices:
        todas = (Evidencia.query
                 .filter(Evidencia.id_aprendiz.in_([a.id_aprendiz for a in aprendices]))
                 .order_by(Evidencia.fecha_entrega.desc()).all())
        for ev in todas:
            evidencias_por_aprendiz.setdefault(ev.id_aprendiz, []).append(ev)

    aprendices_data = []
    for ap in aprendices:
        evidencias = evidencias_por_aprendiz.get(ap.id_aprendiz, [])
        p = calcular_progreso(ap, evidencias_count=len(evidencias))
        aprendices_data.append({
            'aprendiz': ap,
            'pct_tiempo': p['pct_tiempo'],
            'pct_evidencias': p['pct_evidencias'],
            'evidencias_count': p['evidencias_count'],
            'dias_totales': p['dias_totales'],
            'dias_restantes': p['dias_restantes'],
            'periodo_definido': p['periodo_definido'],
            'fecha_inicio': p['fecha_inicio'],
            'fecha_fin': p['fecha_fin'],
            'evidencias': evidencias,
        })

    asignados = [ci.instructor for ci in curso.instructores if ci.instructor]
    ids_asignados = {i.id_instructor for i in asignados}
    disponibles = (Instructor.query.join(Usuario)
                   .filter(Instructor.activo.is_(True))
                   .order_by(Usuario.nombres).all())

    return render_template('admin/fichas/detalle.html',
                           curso=curso,
                           aprendices_data=aprendices_data,
                           instructores=asignados,
                           instructores_disponibles=[i for i in disponibles
                                                     if i.id_instructor not in ids_asignados])


@bp.route('/fichas/<int:id_curso>/remover-aprendiz/<int:id_aprendiz>', methods=['POST'])
@login_required
@role_required('superusuario')
def remover_aprendiz_ficha(id_curso, id_aprendiz):
    """Remover aprendiz del curso (Solo Superusuario)"""
    ca = CursoAprendiz.query.filter_by(
        id_curso=id_curso, id_aprendiz=id_aprendiz).first_or_404()

    curso = ca.curso
    aprendiz = ca.aprendiz
    nombre_ap = aprendiz.usuario.nombres if aprendiz and aprendiz.usuario else id_aprendiz
    db.session.delete(ca)

    log_historial(current_user, 'Fichas Admin', 'MODIFICAR',
                  f'Aprendiz {nombre_ap} removido de la ficha {curso.nombre}')
    db.session.commit()

    flash('Aprendiz removido de la ficha.', 'success')
    return redirect(url_for('admin.ficha_detalle', id_curso=id_curso))
