"""Blueprint Evidencia — gestión auxiliar de evidencias."""
from flask import Blueprint
bp = Blueprint('evidencia', __name__, url_prefix='/evidencia')
# Las rutas de evidencias están integradas en aprendiz e instructor blueprints.
