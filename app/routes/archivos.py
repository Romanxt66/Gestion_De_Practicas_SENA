"""
Blueprint Archivos — entrega controlada de los archivos de evidencia.

Los archivos siguen guardándose en app/static/uploads/evidencias/, pero el
acceso directo por /static/uploads/ está bloqueado (ver app/__init__.py).
Solo pueden descargarse desde aquí, previa validación de permisos:
el aprendiz dueño, un instructor de su ficha, o un superusuario.
"""
import os

from flask import Blueprint, abort, send_from_directory
from flask_login import login_required, current_user

from app.models.evidencia import Evidencia
from app.utils import puede_ver_evidencia, directorio_evidencias

bp = Blueprint('archivos', __name__, url_prefix='/archivos')


@bp.route('/evidencia/<int:id_evidencia>')
@login_required
def evidencia(id_evidencia):
    ev = Evidencia.query.get_or_404(id_evidencia)

    if not puede_ver_evidencia(current_user, ev):
        abort(403)

    if ev.tipo != 'archivo' or not ev.contenido:
        abort(404)

    # contenido guardado como 'uploads/evidencias/<nombre>'
    nombre = os.path.basename(ev.contenido)
    if not nombre:
        abort(404)

    carpeta = directorio_evidencias()
    if not os.path.isfile(os.path.join(carpeta, nombre)):
        abort(404)

    return send_from_directory(carpeta, nombre, as_attachment=False)
