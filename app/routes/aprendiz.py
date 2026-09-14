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
from app.servicios import correo
from app.utils import (role_required, calcular_progreso,
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

        # Avisar a los instructores de sus fichas (el envío corre en segundo plano)
        avisados = set()
        for ca in ap.cursos:
            if not ca.curso:
                continue
            for ci in ca.curso.instructores:
                inst_usuario = ci.instructor.usuario if ci.instructor else None
                if not inst_usuario or not inst_usuario.correo:
                    continue
                clave = (inst_usuario.id_usuario, ca.curso.id_curso)
                if clave in avisados:
                    continue
                avisados.add(clave)
                correo.avisar_evidencia_subida(
                    instructor_usuario=inst_usuario,
                    aprendiz_usuario=current_user,
                    curso_nombre=ca.curso.nombre,
                    tipo_evidencia=tipo,
                )

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
        nombres = request.form.get('nombres', '').strip()
        apellidos = request.form.get('apellidos', '').strip()
        correo = request.form.get('correo', '').strip().lower()
        telefono = request.form.get('telefono', '').strip()
        tipo_documento = request.form.get('tipo_documento', '').strip()
        numero_documento = request.form.get('numero_documento', '').strip()

        if not nombres or not apellidos:
            flash('Nombres y apellidos son obligatorios.', 'danger')
            return redirect(url_for('aprendiz.informacion'))

        if '@' not in correo or '.' not in correo.split('@')[-1]:
            flash('Ingresa un correo electrónico válido.', 'danger')
            return redirect(url_for('aprendiz.informacion'))

        # El correo es además la credencial de acceso: no puede repetirse
        if correo != current_user.correo:
            from app.models.usuario import Usuario
            if Usuario.query.filter_by(correo=correo).first():
                flash('Ya existe una cuenta con ese correo.', 'warning')
                return redirect(url_for('aprendiz.informacion'))

        if telefono and not telefono.replace(' ', '').replace('-', '').replace('+', '').isdigit():
            flash('El teléfono solo puede contener números.', 'danger')
            return redirect(url_for('aprendiz.informacion'))

        cambio_correo = correo != current_user.correo
        current_user.nombres = nombres
        current_user.apellidos = apellidos
        current_user.correo = correo
        current_user.telefono = telefono
        current_user.tipo_documento = tipo_documento or None
        current_user.numero_documento = numero_documento or None
        # La ficha la gestiona el instructor o el administrador: si el aprendiz
        # pudiera cambiarla, dejaría de coincidir con el curso en el que está
        # matriculado.
        db.session.commit()

        flash('Datos actualizados.' + (' A partir de ahora entra con tu nuevo correo.'
                                       if cambio_correo else ''), 'success')
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
