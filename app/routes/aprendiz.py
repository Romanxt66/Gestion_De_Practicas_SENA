"""
Blueprint Aprendiz — 6 módulos:
  /aprendiz/dashboard
  /aprendiz/evidencias/subir
  /aprendiz/progreso
  /aprendiz/informacion
  /aprendiz/notificaciones
  /aprendiz/mis-evidencias
"""
import os
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, current_app)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
from app import db
from app.utils import role_required, enviar_correo_evidencia, make_aware
from app.models.evidencia import Evidencia
from app.models.notificacion import Notificacion
from app.models.progreso_aprendiz import ProgresoAprendiz

bp = Blueprint('aprendiz', __name__, url_prefix='/aprendiz')

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'png', 'jpg', 'jpeg', 'zip', 'txt'}

def _allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def _get_aprendiz():
    return current_user.aprendiz


# ─── Dashboard ────────────────────────────────
@bp.route('/dashboard')
@login_required
@role_required('aprendiz')
def dashboard():
    ap = _get_aprendiz()
    pct_tiempo = 0
    pct_evidencias = 0
    evidencias_count = 0
    if ap and ap.usuario and ap.usuario.fecha_creacion:
        from datetime import datetime, timezone
        dias_transcurridos = (datetime.now(timezone.utc) - make_aware(ap.usuario.fecha_creacion)).days
        pct_tiempo = min(100, max(0, round((dias_transcurridos / 180) * 100, 1)))
        
        evidencias_count = Evidencia.query.filter_by(id_aprendiz=ap.id_aprendiz).count()
        pct_evidencias = min(100, round((evidencias_count / 12) * 100, 1))

    notifs_sin_leer = 0
    if ap:
        notifs_sin_leer = Notificacion.query.filter_by(
            id_usuario=current_user.id_usuario, leida=False).count()

    evidencias_recientes = []
    if ap:
        evidencias_recientes = (Evidencia.query
                                .filter_by(id_aprendiz=ap.id_aprendiz)
                                .order_by(Evidencia.fecha_entrega.desc())
                                .limit(5).all())

    return render_template('aprendiz/dashboard.html',
                           aprendiz=ap,
                           pct_tiempo=pct_tiempo,
                           pct_evidencias=pct_evidencias,
                           evidencias_count=evidencias_count,
                           notifs_sin_leer=notifs_sin_leer,
                           evidencias_recientes=evidencias_recientes)


# ─── Subir evidencias ─────────────────────────
@bp.route('/evidencias/subir', methods=['GET', 'POST'])
@login_required
@role_required('aprendiz')
def evidencias_subir():
    ap = _get_aprendiz()
    if not ap:
        flash('No tienes un perfil de aprendiz registrado.', 'danger')
        return redirect(url_for('aprendiz.dashboard'))

    # Calcular progreso
    pct_tiempo = 0
    pct_evidencias = 0
    evidencias_count = 0
    if ap and ap.usuario and ap.usuario.fecha_creacion:
        from datetime import datetime, timezone
        dias_transcurridos = (datetime.now(timezone.utc) - make_aware(ap.usuario.fecha_creacion)).days
        pct_tiempo = min(100, max(0, round((dias_transcurridos / 180) * 100, 1)))
        
        evidencias_count = Evidencia.query.filter_by(id_aprendiz=ap.id_aprendiz).count()
        pct_evidencias = min(100, round((evidencias_count / 12) * 100, 1))

    if request.method == 'POST':
        tipo = request.form.get('tipo', '')
        contenido = request.form.get('contenido', '').strip()

        if tipo == 'archivo':
            archivo = request.files.get('archivo')
            if not archivo or archivo.filename == '':
                flash('Selecciona un archivo.', 'danger')
                return render_template('aprendiz/evidencias_subir.html', aprendiz=ap, pct_tiempo=pct_tiempo, pct_evidencias=pct_evidencias)
            if not _allowed(archivo.filename):
                flash('Tipo de archivo no permitido.', 'danger')
                return render_template('aprendiz/evidencias_subir.html', aprendiz=ap, pct_tiempo=pct_tiempo, pct_evidencias=pct_evidencias)
            fname = secure_filename(archivo.filename)
            upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'evidencias')
            os.makedirs(upload_dir, exist_ok=True)
            archivo.save(os.path.join(upload_dir, fname))
            contenido = f'uploads/evidencias/{fname}'

        elif tipo == 'enlace':
            if not contenido.startswith('http'):
                flash('El enlace debe comenzar con http:// o https://', 'danger')
                return render_template('aprendiz/evidencias_subir.html', aprendiz=ap, pct_tiempo=pct_tiempo, pct_evidencias=pct_evidencias)
        elif tipo == 'texto':
            if not contenido:
                flash('Escribe el contenido de la evidencia.', 'danger')
                return render_template('aprendiz/evidencias_subir.html', aprendiz=ap, pct_tiempo=pct_tiempo, pct_evidencias=pct_evidencias)
        else:
            flash('Selecciona un tipo de evidencia.', 'danger')
            return render_template('aprendiz/evidencias_subir.html', aprendiz=ap, pct_tiempo=pct_tiempo, pct_evidencias=pct_evidencias)

        evidencia = Evidencia(
            id_aprendiz=ap.id_aprendiz,
            tipo=tipo,
            contenido=contenido,
            estado='Entregada'
        )
        db.session.add(evidencia)
        db.session.commit()
        
        # Notificar a los instructores por correo
        nombre_aprendiz = f"{current_user.nombres} {current_user.apellidos}"
        for ca in ap.cursos:
            nombre_curso = ca.curso.nombre
            for ci in ca.curso.instructores:
                if ci.instructor and ci.instructor.usuario and ci.instructor.usuario.correo:
                    enviar_correo_evidencia(ci.instructor.usuario.correo, nombre_aprendiz, nombre_curso)

        flash('Evidencia enviada correctamente.', 'success')
        return redirect(url_for('aprendiz.mis_evidencias'))

    return render_template('aprendiz/evidencias_subir.html', aprendiz=ap, pct_tiempo=pct_tiempo, pct_evidencias=pct_evidencias)


# ─── Mi Progreso ──────────────────────────────
@bp.route('/progreso')
@login_required
@role_required('aprendiz')
def progreso():
    ap = _get_aprendiz()
    pct_tiempo = 0
    pct_evidencias = 0
    evidencias_count = 0
    dias_transcurridos = 0
    if ap and ap.usuario and ap.usuario.fecha_creacion:
        from datetime import datetime, timezone
        dias_transcurridos = (datetime.now(timezone.utc) - make_aware(ap.usuario.fecha_creacion)).days
        pct_tiempo = min(100, max(0, round((dias_transcurridos / 180) * 100, 1)))
        
        evidencias_count = Evidencia.query.filter_by(id_aprendiz=ap.id_aprendiz).count()
        pct_evidencias = min(100, round((evidencias_count / 12) * 100, 1))

    progreso_cursos = []
    if ap:
        progreso_cursos = (ProgresoAprendiz.query
                           .filter_by(id_aprendiz=ap.id_aprendiz).all())
    return render_template('aprendiz/progreso.html',
                           aprendiz=ap, 
                           pct_tiempo=pct_tiempo,
                           pct_evidencias=pct_evidencias,
                           evidencias_count=evidencias_count,
                           dias_transcurridos=dias_transcurridos,
                           progreso_cursos=progreso_cursos)


# ─── Mi Información ───────────────────────────
@bp.route('/informacion', methods=['GET', 'POST'])
@login_required
@role_required('aprendiz')
def informacion():
    ap = _get_aprendiz()
    if request.method == 'POST':
        current_user.telefono = request.form.get('telefono', '').strip()
        if ap:
            ap.ficha = request.form.get('ficha', '').strip()
        db.session.commit()
        flash('Información actualizada.', 'success')
        return redirect(url_for('aprendiz.informacion'))
    return render_template('aprendiz/informacion.html',
                           aprendiz=ap, usuario=current_user)


# ─── Notificaciones ───────────────────────────
@bp.route('/notificaciones')
@login_required
@role_required('aprendiz')
def notificaciones():
    notifs = (Notificacion.query
              .filter_by(id_usuario=current_user.id_usuario)
              .order_by(Notificacion.fecha.desc()).all())
    # Marcar como leídas
    for n in notifs:
        if not n.leida:
            n.leida = True
    db.session.commit()
    return render_template('aprendiz/notificaciones.html', notificaciones=notifs)


# ─── Mis Evidencias ───────────────────────────
@bp.route('/mis-evidencias')
@login_required
@role_required('aprendiz')
def mis_evidencias():
    ap = _get_aprendiz()
    evidencias = []
    if ap:
        evidencias = (Evidencia.query
                      .filter_by(id_aprendiz=ap.id_aprendiz)
                      .order_by(Evidencia.fecha_entrega.desc()).all())
    return render_template('aprendiz/mis_evidencias.html',
                           aprendiz=ap, evidencias=evidencias)
