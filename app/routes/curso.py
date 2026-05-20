"""Blueprint Curso — stub."""
from flask import Blueprint
bp = Blueprint('curso', __name__, url_prefix='/curso')
# Gestión de cursos accesible desde instructor.mis_cursos.
