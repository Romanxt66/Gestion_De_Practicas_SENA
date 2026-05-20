from app import db
from datetime import datetime, timezone

class AprendizBackup(db.Model):
    __tablename__ = 'aprendiz_backup'
    id_backup      = db.Column(db.Integer, primary_key=True)
    id_aprendiz    = db.Column(db.Integer, db.ForeignKey('aprendiz.id_aprendiz'), unique=True, nullable=False)
    datos          = db.Column(db.Text)
    fecha_respaldo = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    aprendiz       = db.relationship('Aprendiz', back_populates='backup')