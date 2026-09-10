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
                   flash, request)
from flask_login import current_user, login_required

from app import db
from app.models.evidencia import Evidencia
from app.models.notificacion import Notificacion
from app.models.progreso_aprendiz import ProgresoAprendiz
from app.utils import (role_required, enviar_correo_evidencia, calcular_progreso,
                       extension_permitida, nombre_archivo_seguro,
                       directorio_evidencias, EXTENSIONES_PERMITIDAS)

bp = Blueprint('aprendiz', __name__, url_prefix='/aprendiz')


def _get_aprendiz():
    return current_user.aprendiz


# ─── Dashboard ────────────────────────────────
@bp.route('/dashboard')
@login_required
@role_required('aprendiz')
def dashboard():
    ap = _get_aprendiz()
    p = calcular_progreso(ap)

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
                           pct_tiempo=p['pct_tiempo'],
                           pct_evidencias=p['pct_evidencias'],
                           evidencias_count=p['evidencias_count'],
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

    p = calcular_progreso(ap)

    def _volver(mensaje, categoria='danger'):
        flash(mensaje, categoria)
        return render_template('aprendiz/evidencias_subir.html', aprendiz=ap,
                               pct_tiempo=p['pct_tiempo'],
                               pct_evidencias=p['pct_evidencias'])

    if request.method == 'POST':
        tipo = request.form.get('tipo', '')
        contenido = request.form.get('contenido', '').strip()

        if tipo == 'archivo':
            archivo = request.files.get('archivo')
            if not archivo or archivo.filename == '':
                return _volver('Selecciona un archivo.')
            if not extension_permitida(archivo.filename):
                permitidas = ', '.join(sorted(EXTENSIONES_PERMITIDAS))
                return _volver(f'Tipo de archivo no permitido. Permitidos: {permitidas}.')

            # Nombre único: evita que dos aprendices con el mismo nombre de
            # archivo se sobrescriban la evidencia entre sí.
            fname = nombre_archivo_seguro(archivo.filename, ap.id_aprendiz)
            try:
                archivo.save(os.path.join(directorio_evidencias(), fname))
            except OSError as e:
                print(f"Error guardando evidencia: {e}", flush=True)
                return _volver('No se pudo guardar el archivo. Inténtalo de nuevo.')
            contenido = f'uploads/evidencias/{fname}'

        elif tipo == 'enlace':
            if not contenido.startswith(('http://', 'https://')):
                return _volver('El enlace debe comenzar con http:// o https://')
        elif tipo == 'texto':
            if not contenido:
                return _volver('Escribe el contenido de la evidencia.')
        else:
            return _volver('Selecciona un tipo de evidencia.')

        evidencia = Evidencia(
            id_aprendiz=ap.id_aprendiz,
            tipo=tipo,
            contenido=contenido,
            estado='Entregada'
        )
        db.session.add(evidencia)
        db.session.commit()

        # Notificar a los instructores (el envío corre en segundo plano)
        nombre_aprendiz = f"{current_user.nombres} {current_user.apellidos}"
        destinatarios = set()
        for ca in ap.cursos:
            if not ca.curso:
                continue
            for ci in ca.curso.instructores:
                if ci.instructor and ci.instructor.usuario and ci.instructor.usuario.correo:
                    destinatarios.add((ci.instructor.usuario.correo, ca.curso.nombre))
        for correo, nombre_curso in destinatarios:
            enviar_correo_evidencia(correo, nombre_aprendiz, nombre_curso)

        flash('Evidencia enviada correctamente.', 'success')
        return redirect(url_for('aprendiz.mis_evidencias'))

    return render_template('aprendiz/evidencias_subir.html', aprendiz=ap,
                           pct_tiempo=p['pct_tiempo'],
                           pct_evidencias=p['pct_evidencias'])


# ─── Mi Progreso ──────────────────────────────
@bp.route('/progreso')
@login_required
@role_required('aprendiz')
def progreso():
    ap = _get_aprendiz()
    p = calcular_progreso(ap)

    progreso_cursos = []
    if ap:
        progreso_cursos = (ProgresoAprendiz.query
                           .filter_by(id_aprendiz=ap.id_aprendiz).all())
    return render_template('aprendiz/progreso.html',
                           aprendiz=ap,
                           pct_tiempo=p['pct_tiempo'],
                           pct_evidencias=p['pct_evidencias'],
                           evidencias_count=p['evidencias_count'],
                           dias_transcurridos=p['dias_transcurridos'],
                           progreso_cursos=progreso_cursos)


# ─── Mi Información ───────────────────────────
@bp.route('/informacion', methods=['GET', 'POST'])
@login_required
@role_required('aprendiz')
def informacion():
    ap = _get_aprendiz()
    if request.method == 'POST':
        telefono = request.form.get('telefono', '').strip()
        if telefono and not telefono.replace(' ', '').replace('-', '').replace('+', '').isdigit():
            flash('El teléfono solo puede contener números.', 'danger')
            return redirect(url_for('aprendiz.informacion'))
        current_user.telefono = telefono
        # La ficha la asigna el instructor/administrador: el aprendiz no puede
        # cambiarla por su cuenta porque dejaría de coincidir con su curso.
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
    if any(not n.leida for n in notifs):
        for n in notifs:
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
