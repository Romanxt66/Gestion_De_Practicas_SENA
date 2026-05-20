"""
Blueprint Instructor — 7 módulos:
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
                   flash, request)
from flask_login import current_user, login_required
from app import db
from app.utils import role_required, log_historial
from app.models.aprendiz import Aprendiz
from app.models.usuario import Usuario
from app.models.evidencia import Evidencia
from app.models.notificacion import Notificacion
from app.models.progreso_aprendiz import ProgresoAprendiz
from app.models.curso_instructor import CursoInstructor
from app.models.curso_aprendiz import CursoAprendiz
from app.models.curso import Curso
from app.models.empresa import Empresa

bp = Blueprint('instructor', __name__, url_prefix='/instructor')


def _get_instructor():
    return current_user.instructor


def _aprendices_del_instructor():
    """Devuelve lista de Aprendiz que tienen cursos del instructor."""
    inst = _get_instructor()
    if not inst:
        return []
    # Todos los id_curso asignados al instructor
    ids_cursos = [ci.id_curso for ci in inst.cursos]
    if not ids_cursos:
        return []
    ids_aprendiz = db.session.query(CursoAprendiz.id_aprendiz).filter(
        CursoAprendiz.id_curso.in_(ids_cursos)
    ).distinct().all()
    ids_aprendiz = [r[0] for r in ids_aprendiz]
    return Aprendiz.query.filter(Aprendiz.id_aprendiz.in_(ids_aprendiz)).all()


# ─── Dashboard ────────────────────────────────
@bp.route('/dashboard')
@login_required
@role_required('instructor')
def dashboard():
    inst = _get_instructor()
    aprendices = _aprendices_del_instructor()
    evidencias_pendientes = 0
    for ap in aprendices:
        evidencias_pendientes += Evidencia.query.filter_by(
            id_aprendiz=ap.id_aprendiz, estado='Entregada').count()

    # Preparar datos de fichas/cursos
    fichas_data = []
    progreso_general = 0
    total_horas_cumplidas = 0
    total_horas_requeridas = 0
    
    if inst:
        cursos = [ci.curso for ci in inst.cursos]
        for curso in cursos:
            # Contar aprendices en este curso
            aprendices_curso = db.session.query(CursoAprendiz).filter_by(
                id_curso=curso.id_curso).all()
            
            # Contar evidencias pendientes en este curso
            ids_aprendices_curso = [ac.id_aprendiz for ac in aprendices_curso]
            evidencias_pendientes_curso = 0
            if ids_aprendices_curso:
                evidencias_pendientes_curso = db.session.query(Evidencia).filter(
                    Evidencia.id_aprendiz.in_(ids_aprendices_curso),
                    Evidencia.estado == 'Entregada'
                ).count()
            
            fichas_data.append({
                'curso': curso,
                'aprendices_count': len(aprendices_curso),
                'evidencias_pendientes': evidencias_pendientes_curso
            })
            
            # Acumular horas para progreso general
            for ac in aprendices_curso:
                ap = ac.aprendiz
                total_horas_cumplidas += ap.horas_cumplidas or 0
                total_horas_requeridas += ap.horas_requeridas or 0
    
    # Calcular progreso general
    if total_horas_requeridas > 0:
        progreso_general = round((total_horas_cumplidas / total_horas_requeridas) * 100, 1)

    return render_template('instructor/dashboard.html',
                           instructor=inst,
                           total_aprendices=len(aprendices),
                           evidencias_pendientes=evidencias_pendientes,
                           total_cursos=len(inst.cursos) if inst else 0,
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
    
    cursos = [ci.curso for ci in inst.cursos] if inst else []
    
    # Filtrar por búsqueda
    if q:
        cursos = [c for c in cursos if q.lower() in c.nombre.lower()]
    
    # Preparar datos
    fichas_data = []
    for curso in cursos:
        aprendices_curso = db.session.query(CursoAprendiz).filter_by(
            id_curso=curso.id_curso).all()
        
        ids_aprendices_curso = [ac.id_aprendiz for ac in aprendices_curso]
        evidencias_pendientes_curso = 0
        if ids_aprendices_curso:
            evidencias_pendientes_curso = db.session.query(Evidencia).filter(
                Evidencia.id_aprendiz.in_(ids_aprendices_curso),
                Evidencia.estado == 'Entregada'
            ).count()
        
        fichas_data.append({
            'curso': curso,
            'aprendices_count': len(aprendices_curso),
            'evidencias_pendientes': evidencias_pendientes_curso
        })
    
    return render_template('instructor/fichas/index.html',
                           fichas_data=fichas_data, q=q)


@bp.route('/fichas/crear', methods=['POST'])
@login_required
@role_required('instructor')
def crear_ficha():
    """Instructor crea una nueva ficha"""
    nombre = request.form.get('nombre', '').strip()
    ficha = request.form.get('ficha', '').strip()
    fecha_inicio_str = request.form.get('fecha_inicio', '')
    fecha_fin_str = request.form.get('fecha_fin', '')
    
    fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date() if fecha_inicio_str else None
    fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date() if fecha_fin_str else None
    
    if not nombre:
        flash('El nombre es requerido.', 'danger')
        return redirect(url_for('instructor.fichas'))
        
    if Curso.query.filter_by(nombre=nombre).first():
        flash('Ya existe una ficha con ese nombre.', 'warning')
        return redirect(url_for('instructor.fichas'))
        
    if Curso.query.filter_by(ficha=ficha).first():
        flash('Ya existe un código de curso con esa ficha.', 'warning')
        return redirect(url_for('instructor.fichas'))
        
    curso = Curso(nombre=nombre, ficha=ficha,
                  fecha_inicio=fecha_inicio if fecha_inicio else None,
                  fecha_fin=fecha_fin if fecha_fin else None)
    db.session.add(curso)
    db.session.flush()
    
    inst = _get_instructor()
    db.session.add(CursoInstructor(id_curso=curso.id_curso, id_instructor=inst.id_instructor))
    
    log_historial(current_user, 'Fichas Instructor', 'CREAR', f'Ficha {nombre} creada por instructor')
    db.session.commit()
    
    flash('Ficha creada y asignada correctamente.', 'success')
    next_page = request.args.get('next')
    if next_page and next_page == 'instructor.mis_cursos':
        return redirect(url_for('instructor.mis_cursos'))
    return redirect(url_for('instructor.fichas'))


@bp.route('/fichas/<int:id_curso>/detalle')
@login_required
@role_required('instructor')
def ficha_detalle(id_curso):
    """Detalle de ficha: aprendices + evidencias"""
    curso = Curso.query.get_or_404(id_curso)
    
    # Verificar que el instructor tenga este curso
    inst = _get_instructor()
    ids_cursos = [ci.id_curso for ci in inst.cursos] if inst else []
    if id_curso not in ids_cursos:
        flash('No tienes acceso a esta ficha.', 'danger')
        return redirect(url_for('instructor.fichas'))
    
    # Obtener aprendices de este curso
    aprendices_curso = db.session.query(CursoAprendiz).filter_by(
        id_curso=id_curso).all()
    
    aprendices_data = []
    for ca in aprendices_curso:
        ap = ca.aprendiz
        pct = 0
        if ap.horas_requeridas:
            pct = round((ap.horas_cumplidas or 0) / ap.horas_requeridas * 100, 1)
        
        # Evidencias del aprendiz
        evidencias = Evidencia.query.filter_by(
            id_aprendiz=ap.id_aprendiz).order_by(
            Evidencia.fecha_entrega.desc()).all()
        
        aprendices_data.append({
            'aprendiz': ap,
            'progreso': pct,
            'horas_cumplidas': ap.horas_cumplidas,
            'horas_requeridas': ap.horas_requeridas,
            'evidencias': evidencias
        })
    
    empresas = Empresa.query.filter_by(activa=True).all()
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
    empresas = Empresa.query.filter_by(activa=True).all()
    return render_template('instructor/aprendices.html',
                           aprendices=lista, empresas=empresas)


# ─── Asignar empresa al aprendiz ──────────────
@bp.route('/aprendices/<int:id_aprendiz>/empresa', methods=['POST'])
@login_required
@role_required('instructor')
def asignar_empresa(id_aprendiz):
    ap = Aprendiz.query.get_or_404(id_aprendiz)
    id_empresa = request.form.get('id_empresa', type=int)
    ap.id_empresa = id_empresa
    log_historial(current_user, 'Aprendiz', 'MODIFICAR',
                  f'Empresa asignada al aprendiz {id_aprendiz}')
    db.session.commit()
    flash('Empresa asignada correctamente.', 'success')
    next_url = request.form.get('next') or request.referrer or url_for('instructor.aprendices')
    return redirect(next_url)


# ─── Actualizar horas aprendiz ────────────────
@bp.route('/aprendices/<int:id_aprendiz>/horas', methods=['POST'])
@login_required
@role_required('instructor')
def actualizar_horas(id_aprendiz):
    ap = Aprendiz.query.get_or_404(id_aprendiz)
    ap.horas_cumplidas = request.form.get('horas_cumplidas', type=int, default=ap.horas_cumplidas)
    ap.estado_practica = request.form.get('estado_practica', ap.estado_practica)
    log_historial(current_user, 'Aprendiz', 'MODIFICAR',
                  f'Horas actualizadas aprendiz {id_aprendiz}: {ap.horas_cumplidas}h')
    db.session.commit()
    flash('Horas actualizadas.', 'success')
    return redirect(url_for('instructor.aprendices'))


# ─── Revisar Evidencias ───────────────────────
@bp.route('/evidencias/revisar')
@login_required
@role_required('instructor')
def revisar_evidencias():
    aprendices = _aprendices_del_instructor()
    ids = [ap.id_aprendiz for ap in aprendices]
    estado_filtro = request.args.get('estado', 'Entregada')
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
    estado = request.form.get('estado')
    observaciones = request.form.get('observaciones', '').strip()
    
    if estado in ['Aprobada', 'No Aprobada']:
        ev.estado = estado
        if observaciones:
            ev.observaciones = observaciones
        log_historial(current_user, 'Evidencia', 'MODIFICAR',
                      f'Evidencia {id_evidencia} calificada como {estado}')
        db.session.commit()
        if estado == 'Aprobada':
            flash('Evidencia aprobada.', 'success')
        else:
            flash('Evidencia rechazada.', 'warning')
    else:
        flash('Estado de evaluación inválido.', 'danger')
        
    return redirect(url_for('instructor.revisar_evidencias'))


# ─── Progreso Aprendices ──────────────────────
@bp.route('/progreso')
@login_required
@role_required('instructor')
def progreso_aprendices():
    aprendices = _aprendices_del_instructor()
    datos = []
    for ap in aprendices:
        pct = 0
        if ap.horas_requeridas:
            pct = round((ap.horas_cumplidas or 0) / ap.horas_requeridas * 100, 1)
        datos.append({'aprendiz': ap, 'pct': pct})
    return render_template('instructor/progreso_aprendices.html', datos=datos)


# ─── Mis Cursos ───────────────────────────────
@bp.route('/mis-cursos')
@login_required
@role_required('instructor')
def mis_cursos():
    inst = _get_instructor()
    cursos = []
    if inst:
        cursos = [ci.curso for ci in inst.cursos]
    return render_template('instructor/mis_cursos.html', cursos=cursos)


# ─── Enviar Alertas ───────────────────────────
@bp.route('/alertas', methods=['GET', 'POST'])
@login_required
@role_required('instructor')
def alertas():
    aprendices = _aprendices_del_instructor()
    if request.method == 'POST':
        destino = request.form.get('destino')  # 'todos' o id_usuario
        mensaje = request.form.get('mensaje', '').strip()
        if not mensaje:
            flash('Escribe un mensaje.', 'danger')
            return render_template('instructor/alertas.html', aprendices=aprendices)

        if destino == 'todos':
            for ap in aprendices:
                db.session.add(Notificacion(
                    id_usuario=ap.usuario.id_usuario,
                    mensaje=mensaje
                ))
        else:
            db.session.add(Notificacion(
                id_usuario=int(destino),
                mensaje=mensaje
            ))
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
    evidencias = (Evidencia.query
                  .filter(Evidencia.id_aprendiz.in_(ids))
                  .order_by(Evidencia.fecha_entrega.desc()).all())
    return render_template('instructor/reportes.html',
                           aprendices=aprendices,
                           evidencias=evidencias)
