from app import db
from datetime import datetime, timezone

class HistorialCambios(db.Model):
    __tablename__ = 'historial_cambios'
    id_historial = db.Column(db.Integer, primary_key=True)
    id_usuario   = db.Column(db.Integer, db.ForeignKey('usuario.id_usuario'), nullable=False)
    modulo       = db.Column(db.String(50))
    accion       = db.Column(db.Enum('CREAR', 'MODIFICAR', 'ELIMINAR', name='accion_enum'))
    descripcion  = db.Column(db.Text)
    fecha        = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    usuario      = db.relationship('Usuario', back_populates='historial')