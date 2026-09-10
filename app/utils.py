"""
Utilidades compartidas: decoradores de roles, permisos, auditoría, progreso y correo.
"""
import os
import unicodedata
from datetime import datetime, timezone
from functools import wraps

from flask import redirect, url_for, flash, abort, current_app
from flask_login import current_user

from app import db

# ─────────────────────────────────────────────
# Parámetros del cálculo de progreso
# (antes estaban repetidos y hardcodeados en 6 sitios distintos)
# ─────────────────────────────────────────────
DIAS_PRACTICA = 180
EVIDENCIAS_ESPERADAS = 12
HORAS_PRACTICA_POR_DEFECTO = 880

EXTENSIONES_PERMITIDAS = {
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'png', 'jpg', 'jpeg', 'zip', 'txt'
}


# ─────────────────────────────────────────────
# Helper: asegurar compatibilidad de datetime
# ─────────────────────────────────────────────
def make_aware(dt):
    """Convierte un datetime naive a aware con UTC si es necesario."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ─────────────────────────────────────────────
# Decorador de rol
# ─────────────────────────────────────────────
def role_required(*roles):
    """Protege una ruta para que solo usuarios con alguno de los roles dados puedan acceder."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Inicia sesión para continuar.', 'warning')
                return redirect(url_for('auth.login'))
            user_roles = {ur.rol.nombre.lower() for ur in current_user.roles}
            required = {r.lower() for r in roles}
            if not user_roles.intersection(required):
                flash('No tienes permiso para acceder a esa sección.', 'danger')
                return abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator


# ─────────────────────────────────────────────
# Helper: detectar rol principal del usuario
# ─────────────────────────────────────────────
def get_user_role(usuario):
    """Devuelve el rol principal como string ('superusuario' > 'instructor' > 'aprendiz')."""
    nombres = {ur.rol.nombre.lower() for ur in usuario.roles}
    if 'superusuario' in nombres:
        return 'superusuario'
    if 'instructor' in nombres:
        return 'instructor'
    if 'aprendiz' in nombres:
        return 'aprendiz'
    return 'sin_rol'


def es_superusuario(usuario):
    return 'superusuario' in {ur.rol.nombre.lower() for ur in usuario.roles}


# ─────────────────────────────────────────────
# Permisos: qué aprendices/evidencias puede tocar un instructor
# ─────────────────────────────────────────────
def ids_cursos_de_instructor(instructor):
    """IDs de los cursos (fichas) asignados a un instructor."""
    if not instructor:
        return []
    return [ci.id_curso for ci in instructor.cursos]


def ids_aprendices_de_instructor(instructor):
    """IDs de los aprendices matriculados en algún curso del instructor."""
    from app.models.curso_aprendiz import CursoAprendiz
    ids_cursos = ids_cursos_de_instructor(instructor)
    if not ids_cursos:
        return []
    filas = (db.session.query(CursoAprendiz.id_aprendiz)
             .filter(CursoAprendiz.id_curso.in_(ids_cursos))
             .distinct().all())
    return [f[0] for f in filas]


def instructor_puede_gestionar_aprendiz(usuario, id_aprendiz):
    """True si el usuario es superusuario, o instructor de una ficha del aprendiz."""
    if es_superusuario(usuario):
        return True
    return int(id_aprendiz) in ids_aprendices_de_instructor(usuario.instructor)


def puede_ver_evidencia(usuario, evidencia):
    """True si el usuario es el aprendiz dueño, su instructor, o un superusuario."""
    if es_superusuario(usuario):
        return True
    if usuario.aprendiz and usuario.aprendiz.id_aprendiz == evidencia.id_aprendiz:
        return True
    if usuario.instructor:
        return evidencia.id_aprendiz in ids_aprendices_de_instructor(usuario.instructor)
    return False


# ─────────────────────────────────────────────
# Progreso del aprendiz (fuente única de verdad)
# ─────────────────────────────────────────────
def calcular_progreso(aprendiz, evidencias_count=None):
    """Calcula el progreso de un aprendiz.

    Devuelve un dict con: dias_transcurridos, pct_tiempo, pct_evidencias,
    evidencias_count y pct_general. Si `evidencias_count` se pasa desde fuera
    (por ejemplo, precalculado en lote), se evita una consulta extra.
    """
    vacio = {'dias_transcurridos': 0, 'pct_tiempo': 0.0, 'pct_evidencias': 0.0,
             'evidencias_count': 0, 'pct_general': 0.0}
    if not aprendiz:
        return vacio

    if evidencias_count is None:
        from app.models.evidencia import Evidencia
        evidencias_count = (db.session.query(Evidencia)
                            .filter_by(id_aprendiz=aprendiz.id_aprendiz).count())

    dias = 0
    if aprendiz.usuario and aprendiz.usuario.fecha_creacion:
        dias = (datetime.now(timezone.utc)
                - make_aware(aprendiz.usuario.fecha_creacion)).days

    pct_tiempo = min(100, max(0, round((dias / DIAS_PRACTICA) * 100, 1)))
    pct_evidencias = min(100, max(0, round(
        (evidencias_count / EVIDENCIAS_ESPERADAS) * 100, 1)))

    return {
        'dias_transcurridos': dias,
        'pct_tiempo': pct_tiempo,
        'pct_evidencias': pct_evidencias,
        'evidencias_count': evidencias_count,
        'pct_general': round((pct_tiempo + pct_evidencias) / 2, 1),
    }


def contar_evidencias_por_aprendiz(ids_aprendices, estado=None):
    """Cuenta evidencias agrupando en UNA sola consulta (evita el N+1).

    Devuelve un dict {id_aprendiz: cantidad}; los aprendices sin evidencias
    quedan en 0.
    """
    from app.models.evidencia import Evidencia
    base = {int(i): 0 for i in ids_aprendices}
    if not base:
        return base
    q = (db.session.query(Evidencia.id_aprendiz, db.func.count(Evidencia.id_evidencia))
         .filter(Evidencia.id_aprendiz.in_(list(base.keys()))))
    if estado:
        q = q.filter(Evidencia.estado == estado)
    for id_aprendiz, total in q.group_by(Evidencia.id_aprendiz).all():
        base[int(id_aprendiz)] = int(total)
    return base


def progreso_de_aprendices(aprendices, estado=None):
    """Calcula el progreso de una lista de aprendices con 1 sola consulta de conteo."""
    conteos = contar_evidencias_por_aprendiz(
        [a.id_aprendiz for a in aprendices], estado=estado)
    datos = []
    for ap in aprendices:
        p = calcular_progreso(ap, evidencias_count=conteos.get(ap.id_aprendiz, 0))
        datos.append({
            'aprendiz': ap,
            'pct_tiempo': p['pct_tiempo'],
            'pct_evidencias': p['pct_evidencias'],
            'evidencias_count': p['evidencias_count'],
            'dias_transcurridos': p['dias_transcurridos'],
            'pct_general': p['pct_general'],
        })
    return datos


# ─────────────────────────────────────────────
# Archivos subidos
# ─────────────────────────────────────────────
def directorio_evidencias():
    """Carpeta física donde se guardan los archivos de evidencia."""
    ruta = os.path.join(current_app.root_path, 'static', 'uploads', 'evidencias')
    os.makedirs(ruta, exist_ok=True)
    return ruta


def extension_permitida(filename):
    return ('.' in filename
            and filename.rsplit('.', 1)[1].lower() in EXTENSIONES_PERMITIDAS)


def nombre_archivo_seguro(filename, id_aprendiz):
    """Genera un nombre único y seguro para el archivo subido.

    Antes se usaba solo secure_filename(), así que dos aprendices que subieran
    'informe.pdf' se sobrescribían el archivo entre sí.
    """
    from werkzeug.utils import secure_filename
    base = secure_filename(filename) or 'archivo'
    # Normaliza acentos que secure_filename ya elimina, por si acaso
    base = unicodedata.normalize('NFKD', base).encode('ascii', 'ignore').decode()
    nombre, _, ext = base.rpartition('.')
    if not nombre:
        nombre, ext = base, ''
    nombre = nombre[:60]
    marca = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    sufijo = f'{id_aprendiz}_{marca}'
    return f'{nombre}_{sufijo}.{ext}' if ext else f'{nombre}_{sufijo}'


# ─────────────────────────────────────────────
# Helper: registrar auditoría en historial
# ─────────────────────────────────────────────
def log_historial(usuario, modulo: str, accion: str, descripcion: str = ''):
    """Crea un registro de auditoría en historial_cambios."""
    from app.models.historial_cambios import HistorialCambios
    entry = HistorialCambios(
        id_usuario=usuario.id_usuario,
        modulo=modulo,
        accion=accion.upper(),
        descripcion=descripcion,
        fecha=datetime.now(timezone.utc)
    )
    db.session.add(entry)
    # No hacemos commit aquí; el caller lo hace junto con su transacción principal


# ─────────────────────────────────────────────
# Helper: enviar correo de notificación (Evidencia)
# ─────────────────────────────────────────────
def _enviar_correo(config, destinatario, asunto, contenido):
    """Envío SMTP real. Se ejecuta en un hilo aparte para no bloquear la petición."""
    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg['Subject'] = asunto
    msg['From'] = config['usuario']
    msg['To'] = destinatario
    msg.set_content(contenido)

    try:
        if config['ssl']:
            with smtplib.SMTP_SSL(config['servidor'], config['puerto'],
                                  timeout=config['timeout']) as server:
                server.login(config['usuario'], config['password'])
                server.send_message(msg)
        else:
            with smtplib.SMTP(config['servidor'], config['puerto'],
                              timeout=config['timeout']) as server:
                server.starttls()
                server.login(config['usuario'], config['password'])
                server.send_message(msg)
        return True
    except Exception as e:
        print(f"Error al enviar correo a {destinatario}: {e}", flush=True)
        return False


def enviar_correo_evidencia(destinatario: str, aprendiz_nombre: str, curso_nombre: str):
    """Notifica al instructor que se subió una evidencia.

    El envío se hace en segundo plano: antes bloqueaba la petición del aprendiz
    hasta que Gmail respondiera (y una vez por cada instructor de la ficha).
    """
    import threading

    cfg = {
        'usuario': current_app.config.get('MAIL_USERNAME'),
        'password': current_app.config.get('MAIL_PASSWORD'),
        'servidor': current_app.config.get('MAIL_SERVER'),
        'puerto': current_app.config.get('MAIL_PORT'),
        'ssl': current_app.config.get('MAIL_USE_SSL'),
        'timeout': current_app.config.get('MAIL_TIMEOUT', 10),
    }

    if not cfg['usuario'] or not cfg['password']:
        print("Advertencia: faltan MAIL_USERNAME/MAIL_PASSWORD. Correo no enviado.",
              flush=True)
        return False

    asunto = f"Nueva Evidencia Subida - {curso_nombre}"
    contenido = f"""Hola,

El aprendiz {aprendiz_nombre} ha subido una nueva evidencia para el curso {curso_nombre}.

Por favor, ingresa al sistema para revisarla.

Saludos,
Sistema de Gestión"""

    hilo = threading.Thread(
        target=_enviar_correo,
        args=(cfg, destinatario, asunto, contenido),
        daemon=True,
    )
    hilo.start()
    return True
