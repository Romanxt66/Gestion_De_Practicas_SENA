from app import db
from datetime import datetime, timezone

class Evidencia(db.Model):
    __tablename__ = 'evidencia'
    id_evidencia   = db.Column(db.Integer, primary_key=True)
    id_aprendiz    = db.Column(db.Integer, db.ForeignKey('aprendiz.id_aprendiz'), nullable=False)
    tipo           = db.Column(db.Enum('archivo', 'enlace', 'texto', name='tipo_evidencia_enum'), nullable=False)
    contenido      = db.Column(db.Text)
    fecha_entrega  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    estado         = db.Column(db.Enum('Entregada', 'Revisada', 'Aprobada', 'No Aprobada', name='estado_evidencia_enum'))
    observaciones  = db.Column(db.Text)
    bitacora       = db.Column(db.String(25))
    actas          = db.Column(db.String(25))

    aprendiz       = db.relationship('Aprendiz', back_populates='evidencias')