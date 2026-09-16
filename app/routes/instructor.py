"""
Blueprint Instructor — módulos:
  /instructor/dashboard
  /instructor/fichas
  /instructor/fichas/<id>/detalle
  /instructor/aprendices
  /instructor/evidencias/revisar
  /instructor/progreso
  /instructor/mis-cursos
  /instructor/alertas
  /instructor/reportes
"""
from datetime import datetime

from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, abort)
from flask_login import current_user, login_required

from app import db
from app.servicios import correo
from app.models.aprendiz import Aprendiz
from app.models.curso import Curso
from app.models.curso_aprendiz import CursoAprendiz
from app.models.curso_instructor import CursoInstructor
from app.models.empresa import Empresa
from app.models.evidencia import Evidencia
from app.models.notificacion import Notificacion
from app.utils import (role_required, log_historial, calcular_progreso,
                       progreso_de_aprendices, contar_evidencias_por_aprendiz,
                       ids_cursos_de_instructor, ids_aprendices_de_instructor,
                       matricular_pendientes, resumen_curso,
                       indice_aprobacion, evidencias_entregadas_hoy,
                       origen_de_aprendices, ESTADOS_PRACTICA)

bp = Blueprint('instructor', __name__, url_prefix='/instructor')

ESTADOS_EVIDENCIA = ['Entregada', 'Revisada', 'Aprobada', 'No Aprobada']


def _get_instructor():
    return current_user.instructor


def _aprendices_del_instructor():
    """Devuelve lista de Aprendiz que tienen cursos del instructor."""
    ids_aprendiz = ids_aprendices_de_instructor(_get_instructor())
    if not ids_aprendiz:
        return []
    return Aprendiz.query.filter(Aprendiz.id_aprendiz.in_(ids_aprendiz)).all()


def _exigir_acceso_a_aprendiz(id_aprendiz):
    """Corta la petición si el aprendiz no pertenece a una ficha del instructor.

    Sin esto, cualquier instructor podía modificar a cualquier aprendiz del
    sistema cambiando el ID en la URL.
    """
    if int(id_aprendiz) not in ids_aprendices_de_instructor(_get_instructor()):
        abort(403)


def _exigir_acceso_a_curso(id_curso):
    if int(id_curso) not in ids_cursos_de_instructor(_get_instructor()):
        abort(403)


def _datos_fichas(cursos):
    """Arma la tarjeta de cada ficha (aprendices, pendientes, estado y avance).

    Usa consultas agregadas en lugar de un COUNT por ficha y por aprendiz.
    """
    if not cursos:
        return []
    ids_cursos = [c.id_curso for c in cursos]

    # aprendices por curso, en una consulta
    matriculas = (db.session.query(CursoAprendiz.id_curso, CursoAprendiz.id_aprendiz)
                  .filter(CursoAprendiz.id_curso.in_(ids_cursos)).all())
    por_curso = {}
    for id_curso, id_aprendiz in matriculas:
        por_curso.setdefault(id_curso, []).append(id_aprendiz)

    # evidencias pendientes de todos esos aprendices, en una consulta
    todos_aprendices = {ida for _, ida in matriculas}
    pendientes = contar_evidencias_por_aprendiz(todos_aprendices, estado='Entregada')

    datos = []
    for curso in cursos:
        ids = por_curso.get(curso.id_curso, [])
        fila = {
            'curso': curso,
            'aprendices_count': len(ids),
            'evidencias_pendientes': sum(pendientes.get(i, 0) for i in ids),
        }
        fila.update(resumen_curso(curso))
        datos.append(fila)
    return datos


# ─── Dashboard ────────────────────────────────
@bp.route('/dashboard')
@login_required
@role_required('instructor')
def dashboard():
    inst = _get_instructor()
    aprendices = _aprendices_del_instructor()

    pendientes = contar_evidencias_por_aprendiz(
        [ap.id_aprendiz for ap in aprendices], estado='Entregada')
    evidencias_pendientes = sum(pendientes.values())

    cursos = [ci.curso for ci in inst.cursos if ci.curso] if inst else []
    fichas_data = _datos_fichas(cursos)

    datos_progreso = progreso_de_aprendices(aprendices)
    progreso_general = 0
    if datos_progreso:
        progreso_general = round(
            sum(d['pct_general'] for d in datos_progreso) / len(datos_progreso), 1)

    ids_aprendices = [ap.id_aprendiz for ap in aprendices]
    return render_template('instructor/dashboard.html',
                           instructor=inst,
                           total_aprendices=len(aprendices),
                           evidencias_pendientes=evidencias_pendientes,
                           entregadas_hoy=evidencias_entregadas_hoy(ids_aprendices),
                           indice_aprobacion=indice_aprobacion(ids_aprendices),
                           total_cursos=len(cursos),
                           cursos_en_marcha=sum(1 for f in fichas_data
                                                if f['estado'] == 'en_curso'),
                           fichas_data=fichas_data,
                           progreso_general=progreso_general)


# ─── Fichas del Instructor ────────────────────
@bp.route('/fichas')
@login_required
@role_required('instructor')
def fichas():
    """Listado de fichas/cursos del instructor con búsqueda"""
    q = request.args.get('q', '').strip()
    inst = _get_instructor()

    cursos = [ci.curso for ci in inst.cursos if ci.curso] if inst else []

    if q:
        termino = q.lower()
        cursos = [c for c in cursos
                  if termino in (c.nombre or '').lower()
                  or termino in (c.ficha or '').lower()]

    return render_template('instructor/fichas/index.html',
                           fichas_data=_datos_fichas(cursos), q=q)


@bp.route('/fichas/crear', methods=['POST'])
@login_required
@role_required('instructor')
def crear_ficha():
    """Instructor crea una nueva ficha"""
    inst = _get_instructor()
    if not inst:
        flash('No tienes un perfil de instructor registrado.', 'danger')
        return redirect(url_for('instructor.dashboard'))

    nombre = request.form.get('nombre', '').strip()
    ficha = request.form.get('ficha', '').strip()

    if not nombre:
        flash('El nombre es requerido.', 'danger')
        return redirect(url_for('instructor.fichas'))

    try:
        fecha_inicio = _parse_fecha(request.form.get('fecha_inicio', ''))
        fecha_fin = _parse_fecha(request.form.get('fecha_fin', ''))
    except ValueError:
        flash('Formato de fecha inválido.', 'danger')
        return redirect(url_for('instructor.fichas'))

    if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
        flash('La fecha de fin no puede ser anterior a la de inicio.', 'danger')
        return redirect(url_for('instructor.fichas'))

    if Curso.query.filter_by(nombre=nombre).first():
        flash('Ya existe una ficha con ese nombre.', 'warning')
        return redirect(url_for('instructor.fichas'))

    if ficha and Curso.query.filter_by(ficha=ficha).first():
        flash('Ya existe un código de curso con esa ficha.', 'warning')
        return redirect(url_for('instructor.fichas'))

    curso = Curso(nombre=nombre, ficha=ficha or None,
                  fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
    db.session.add(curso)
    db.session.flush()

    db.session.add(CursoInstructor(id_curso=curso.id_curso,
                                   id_instructor=inst.id_instructor))
    esperando = matricular_pendientes(curso)

    log_historial(current_user, 'Fichas Instructor', 'CREAR',
                  f'Ficha {nombre} creada por instructor')
    db.session.commit()

    if esperando:
        flash(f'Ficha creada y asignada. Se matricularon {len(esperando)} '
              f'aprendiz{"" if len(esperando) == 1 else "es"} que la esperaban.',
              'success')
    else:
        flash('Ficha creada y asignada correctamente.', 'success')
    if request.args.get('next') == 'instructor.mis_cursos':
        return redirect(url_for('instructor.mis_cursos'))
    return redirect(url_for('instructor.fichas'))


@bp.route('/fichas/<int:id_curso>/detalle')
@login_required
@role_required('instructor')
def ficha_detalle(id_curso):
    """Detalle de ficha: aprendices + evidencias"""
    curso = Curso.query.get_or_404(id_curso)
    _exigir_acceso_a_curso(id_curso)

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

    empresas = Empresa.query.filter_by(activa=True).order_by(Empresa.nombre).all()
    return render_template('instructor/fichas/detalle.html',
                           curso=curso,
                           aprendices_data=aprendices_data,
                           empresas=empresas)


# ─── Mis Aprendices ───────────────────────────
@bp.route('/aprendices')
@login_required
@role_required('instructor')
def aprendices():
    lista = _aprendices_del_instructor()
    empresas = Empresa.query.filter_by(activa=True).order_by(Empresa.nombre).all()
    return render_template('instructor/aprendices.html',
                           aprendices_data=progreso_de_aprendices(lista),
                           origen=origen_de_aprendices(_get_instructor()),
                           empresas=empresas)


# ─── Asignar empresa al aprendiz ──────────────
@bp.route('/aprendices/<int:id_aprendiz>/empresa', methods=['POST'])
@login_required
@role_required('instructor')
def asignar_empresa(id_aprendiz):
    _exigir_acceso_a_aprendiz(id_aprendiz)
    ap = Aprendiz.query.get_or_404(id_aprendiz)

    id_empresa = request.form.get('id_empresa', type=int)
    if id_empresa:
        empresa = Empresa.query.get(id_empresa)
        if not empresa or not empresa.activa:
            flash('La empresa seleccionada no existe o está inactiva.', 'danger')
            return redirect(_destino_seguro())
        ap.id_empresa = id_empresa
        detalle = f'Empresa {empresa.nombre} asignada al aprendiz {id_aprendiz}'
        mensaje = 'Empresa asignada correctamente.'
    else:
        ap.id_empresa = None
        detalle = f'Empresa removida del aprendiz {id_aprendiz}'
        mensaje = 'Empresa removida del aprendiz.'

    log_historial(current_user, 'Aprendiz', 'MODIFICAR', detalle)
    db.session.commit()
    flash(mensaje, 'success')
    return redirect(_destino_seguro())


# ─── Actualizar estado y periodo de práctica del aprendiz ──
@bp.route('/aprendices/<int:id_aprendiz>/horas', methods=['POST'])
@login_required
@role_required('instructor')
def actualizar_horas(id_aprendiz):
    _exigir_acceso_a_aprendiz(id_aprendiz)
    ap = Aprendiz.query.get_or_404(id_aprendiz)
    destino = _destino_seguro()

    estado = request.form.get('estado_practica', '').strip()
    if estado and estado not in ESTADOS_PRACTICA:
        flash('Estado de práctica inválido.', 'danger')
        return redirect(destino)

    try:
        inicio = _parse_fecha(request.form.get('fecha_inicio_practica', '').strip())
        fin = _parse_fecha(request.form.get('fecha_fin_practica', '').strip())
    except ValueError:
        flash('Formato de fecha inválido.', 'danger')
        return redirect(destino)

    if inicio and fin and fin <= inicio:
        flash('La fecha de finalización debe ser posterior a la de inicio.', 'danger')
        return redirect(destino)

    cambios = []
    if estado and estado != ap.estado_practica:
        ap.estado_practica = estado
        cambios.append(f'estado: {estado}')

    if inicio != ap.fecha_inicio_practica:
        ap.fecha_inicio_practica = inicio
        cambios.append(f'inicio de práctica: {inicio or "sin definir"}')

    if fin != ap.fecha_fin_practica:
        ap.fecha_fin_practica = fin
        cambios.append(f'fin de práctica: {fin or "sin definir"}')

    if not cambios:
        flash('No hubo cambios que guardar.', 'info')
        return redirect(destino)

    log_historial(current_user, 'Aprendiz', 'MODIFICAR',
                  f'Aprendiz {id_aprendiz} — ' + '; '.join(cambios))
    db.session.commit()
    flash('Datos de la práctica actualizados correctamente.', 'success')
    return redirect(destino)


# ─── Revisar Evidencias ───────────────────────
@bp.route('/evidencias/revisar')
@login_required
@role_required('instructor')
def revisar_evidencias():
    ids = ids_aprendices_de_instructor(_get_instructor())
    estado_filtro = request.args.get('estado', 'Entregada')
    if estado_filtro not in ESTADOS_EVIDENCIA:
        estado_filtro = 'Entregada'

    evidencias = []
    if ids:
        evidencias = (Evidencia.query
                      .filter(Evidencia.id_aprendiz.in_(ids),
                              Evidencia.estado == estado_filtro)
                      .order_by(Evidencia.fecha_entrega.desc()).all())
    return render_template('instructor/revisar_evidencias.html',
                           evidencias=evidencias,
                           estado_filtro=estado_filtro)


@bp.route('/evidencias/<int:id_evidencia>/evaluar', methods=['POST'])
@login_required
@role_required('instructor')
def evaluar_evidencia(id_evidencia):
    ev = Evidencia.query.get_or_404(id_evidencia)
    # La evidencia debe pertenecer a un aprendiz de una ficha del instructor
    _exigir_acceso_a_aprendiz(ev.id_aprendiz)

    estado = request.form.get('estado')
    observaciones = request.form.get('observaciones', '').strip()

    if estado in ('Aprobada', 'No Aprobada'):
        ev.estado = estado
        if observaciones:
            ev.observaciones = observaciones
        log_historial(current_user, 'Evidencia', 'MODIFICAR',
                      f'Evidencia {id_evidencia} calificada como {estado}')
        aprendiz_usuario = ev.aprendiz.usuario if ev.aprendiz else None
        if aprendiz_usuario:
            db.session.add(Notificacion(
                id_usuario=aprendiz_usuario.id_usuario,
                mensaje=f'Tu evidencia del {ev.fecha_entrega:%d/%m/%Y} fue marcada como '
                        f'"{estado}".' + (f' Observaciones: {observaciones}' if observaciones else '')
            ))
        db.session.commit()

        # Avisar por correo al aprendiz (en segundo plano)
        if aprendiz_usuario and aprendiz_usuario.correo:
            correo.avisar_evidencia_calificada(
                aprendiz_usuario=aprendiz_usuario,
                instructor_usuario=current_user,
                estado=estado,
                observaciones=observaciones,
                fecha_entrega=ev.fecha_entrega,
            )
        flash('Evidencia aprobada.' if estado == 'Aprobada' else 'Evidencia rechazada.',
              'success' if estado == 'Aprobada' else 'warning')
    else:
        flash('Estado de evaluación inválido.', 'danger')

    return redirect(url_for('instructor.revisar_evidencias'))


# ─── Progreso Aprendices ──────────────────────
@bp.route('/progreso')
@login_required
@role_required('instructor')
def progreso_aprendices():
    datos = progreso_de_aprendices(_aprendices_del_instructor())
    # La plantilla usa la clave 'evs'
    for d in datos:
        d['evs'] = d['evidencias_count']
    return render_template('instructor/progreso_aprendices.html', datos=datos)


# ─── Mis Cursos ───────────────────────────────
@bp.route('/mis-cursos')
@login_required
@role_required('instructor')
def mis_cursos():
    inst = _get_instructor()
    cursos = [ci.curso for ci in inst.cursos if ci.curso] if inst else []
    return render_template('instructor/mis_cursos.html', cursos=cursos)


# ─── Enviar Alertas ───────────────────────────
@bp.route('/alertas', methods=['GET', 'POST'])
@login_required
@role_required('instructor')
def alertas():
    aprendices = _aprendices_del_instructor()
    if request.method == 'POST':
        destino = request.form.get('destino', '')
        mensaje = request.form.get('mensaje', '').strip()

        if not mensaje:
            flash('Escribe un mensaje.', 'danger')
            return render_template('instructor/alertas.html', aprendices=aprendices)

        if destino == 'todos':
            if not aprendices:
                flash('No tienes aprendices a quienes enviar la alerta.', 'warning')
                return render_template('instructor/alertas.html', aprendices=aprendices)
            for ap in aprendices:
                if ap.usuario:
                    db.session.add(Notificacion(id_usuario=ap.usuario.id_usuario,
                                                mensaje=mensaje))
        else:
            # Solo se puede notificar a aprendices propios
            permitidos = {ap.usuario.id_usuario for ap in aprendices if ap.usuario}
            try:
                id_destino = int(destino)
            except (TypeError, ValueError):
                flash('Destinatario inválido.', 'danger')
                return render_template('instructor/alertas.html', aprendices=aprendices)
            if id_destino not in permitidos:
                abort(403)
            db.session.add(Notificacion(id_usuario=id_destino, mensaje=mensaje))

        db.session.commit()
        flash('Alerta enviada correctamente.', 'success')
        return redirect(url_for('instructor.alertas'))

    return render_template('instructor/alertas.html', aprendices=aprendices)


# ─── Reportes ─────────────────────────────────
@bp.route('/reportes')
@login_required
@role_required('instructor')
def reportes():
    aprendices = _aprendices_del_instructor()
    ids = [ap.id_aprendiz for ap in aprendices]
    evidencias = []
    if ids:
        evidencias = (Evidencia.query
                      .filter(Evidencia.id_aprendiz.in_(ids))
                      .order_by(Evidencia.fecha_entrega.desc()).all())
    return render_template('instructor/reportes.html',
                           aprendices=aprendices,
                           evidencias=evidencias)


# ─── Helpers internos ─────────────────────────
def _parse_fecha(valor):
    return datetime.strptime(valor, '%Y-%m-%d').date() if valor else None


def _destino_seguro():
    """Redirección post-formulario, evitando redirigir a un dominio externo."""
    destino = request.form.get('next') or request.referrer
    if destino and destino.startswith('/') and not destino.startswith('//'):
        return destino
    return url_for('instructor.aprendices')
