from app import db
from datetime import datetime, timezone

class Notificacion(db.Model):
    __tablename__ = 'notificacion'
    id_notificacion = db.Column(db.Integer, primary_key=True)
    id_usuario      = db.Column(db.Integer, db.ForeignKey('usuario.id_usuario'), nullable=False)
    mensaje         = db.Column(db.Text)
    leida           = db.Column(db.Boolean, default=False)
    fecha           = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    usuario         = db.relationship('Usuario', back_populates='notificaciones')