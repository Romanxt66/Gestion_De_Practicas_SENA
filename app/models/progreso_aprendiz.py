from app import db
from datetime import datetime, timezone

class ProgresoAprendiz(db.Model):
    __tablename__ = 'progreso_aprendiz'
    id_progreso          = db.Column(db.Integer, primary_key=True)
    id_aprendiz          = db.Column(db.Integer, db.ForeignKey('aprendiz.id_aprendiz'), nullable=False)
    id_curso             = db.Column(db.Integer, db.ForeignKey('curso.id_curso'), nullable=False)
    porcentaje           = db.Column(db.Numeric(5, 2))
    ultima_actualizacion = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    aprendiz             = db.relationship('Aprendiz', back_populates='progreso')
    curso                = db.relationship('Curso', back_populates='progreso')