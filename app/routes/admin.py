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
from app.utils import (role_required, log_historial, calcular_progreso,
                       directorio_evidencias, HORAS_PRACTICA_POR_DEFECTO)

bp = Blueprint('admin', __name__, url_prefix='/admin')

LONGITUD_MINIMA_PASSWORD = 6


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _parse_fecha(valor):
    return datetime.strptime(valor, '%Y-%m-%d').date() if valor else None


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
    total_fichas       = Curso.query.count()
    total_aprendices   = Aprendiz.query.count()
    total_instructores = Instructor.query.count()
    total_empresas     = Empresa.query.filter_by(activa=True).count()
    cambios_recientes  = (HistorialCambios.query
                          .order_by(HistorialCambios.fecha.desc())
                          .limit(10).all())
    return render_template('admin/dashboard.html',
                           total_usuarios=total_usuarios,
                           total_fichas=total_fichas,
                           total_aprendices=total_aprendices,
                           total_instructores=total_instructores,
                           total_empresas=total_empresas,
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
    return render_template('admin/usuarios.html', usuarios=lista, roles=roles, q=q,
                           resumen=_resumen_borrado(lista))


@bp.route('/usuarios/crear', methods=['POST'])
@login_required
@role_required('superusuario')
def crear_usuario():
    nombres   = request.form.get('nombres', '').strip()
    apellidos = request.form.get('apellidos', '').strip()
    correo    = request.form.get('correo', '').strip().lower()
    password  = request.form.get('password', '')
    id_rol    = request.form.get('id_rol', type=int)

    if not nombres or not apellidos or not correo:
        flash('Nombres, apellidos y correo son obligatorios.', 'danger')
        return redirect(url_for('admin.usuarios'))

    if len(password) < LONGITUD_MINIMA_PASSWORD:
        flash(f'La contraseña debe tener al menos {LONGITUD_MINIMA_PASSWORD} caracteres.',
              'danger')
        return redirect(url_for('admin.usuarios'))

    if Usuario.query.filter_by(correo=correo).first():
        flash('Ya existe un usuario con ese correo.', 'warning')
        return redirect(url_for('admin.usuarios'))

    rol = Rol.query.get(id_rol) if id_rol else None
    if id_rol and not rol:
        flash('El rol seleccionado no existe.', 'danger')
        return redirect(url_for('admin.usuarios'))

    u = Usuario(nombres=nombres, apellidos=apellidos, correo=correo,
                password_hash=generate_password_hash(password), estado=True)
    db.session.add(u)
    db.session.flush()

    if rol:
        db.session.add(UsuarioRol(id_usuario=u.id_usuario, id_rol=rol.id_rol))
        if rol.nombre == 'aprendiz':
            db.session.add(Aprendiz(id_usuario=u.id_usuario,
                                    estado_practica='En proceso',
                                    horas_requeridas=HORAS_PRACTICA_POR_DEFECTO,
                                    horas_cumplidas=0))
        elif rol.nombre == 'instructor':
            db.session.add(Instructor(id_usuario=u.id_usuario, activo=True))

    log_historial(current_user, 'Usuarios', 'CREAR', f'Usuario {correo} creado')
    db.session.commit()
    flash(f'Usuario {nombres} {apellidos} creado.', 'success')
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

    if not nombres or not apellidos or not correo:
        flash('Nombres, apellidos y correo son obligatorios.', 'danger')
        return redirect(url_for('admin.usuarios'))

    if correo != u.correo and Usuario.query.filter_by(correo=correo).first():
        flash('Ya existe otro usuario con ese correo.', 'warning')
        return redirect(url_for('admin.usuarios'))

    if password and len(password) < LONGITUD_MINIMA_PASSWORD:
        flash(f'La contraseña debe tener al menos {LONGITUD_MINIMA_PASSWORD} caracteres.',
              'danger')
        return redirect(url_for('admin.usuarios'))

    u.nombres = nombres
    u.apellidos = apellidos
    u.correo = correo
    u.telefono = telefono

    if password:
        u.password_hash = generate_password_hash(password)

    log_historial(current_user, 'Usuarios', 'MODIFICAR', f'Usuario {correo} editado')
    db.session.commit()
    flash(f'Usuario {nombres} {apellidos} actualizado.', 'success')
    return redirect(url_for('admin.usuarios'))


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
    u = Usuario.query.get_or_404(id_usuario)

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
    return render_template('admin/instructores.html', instructores=lista)


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


@bp.route('/instructores/<int:id_instructor>/area', methods=['POST'])
@login_required
@role_required('superusuario')
def editar_area_instructor(id_instructor):
    inst = Instructor.query.get_or_404(id_instructor)
    inst.area_formacion = request.form.get('area_formacion', '').strip()
    log_historial(current_user, 'Instructores', 'MODIFICAR',
                  f'Área instructor {id_instructor}: {inst.area_formacion}')
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
    log_historial(current_user, 'Fichas', 'CREAR', f'Ficha {nombre} creada')
    db.session.commit()

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
        return redirect(url_for('admin.fichas'))

    instructor = Instructor.query.get_or_404(id_instructor)

    if CursoInstructor.query.filter_by(id_curso=id_curso,
                                       id_instructor=id_instructor).first():
        flash('Este instructor ya está asignado a la ficha.', 'warning')
        return redirect(url_for('admin.fichas'))

    db.session.add(CursoInstructor(id_curso=id_curso, id_instructor=id_instructor))
    log_historial(current_user, 'Fichas', 'MODIFICAR',
                  f'Instructor {instructor.usuario.nombres} asignado a {curso.nombre}')
    db.session.commit()

    flash('Instructor asignado correctamente.', 'success')
    return redirect(url_for('admin.fichas'))


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

    flash('Instructor removido de la ficha.', 'success')
    return redirect(url_for('admin.fichas'))


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

    return render_template('admin/fichas/detalle.html',
                           curso=curso,
                           aprendices_data=aprendices_data)


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
