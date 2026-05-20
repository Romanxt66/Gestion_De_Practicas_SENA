"""Blueprint Notificacion — alertas auxiliar."""
from flask import Blueprint
bp = Blueprint('notificacion', __name__, url_prefix='/notificacion')
# La lógica de notificaciones está en instructor.alertas y aprendiz.notificaciones.
