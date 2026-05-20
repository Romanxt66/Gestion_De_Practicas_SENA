from app import db
from flask_login import UserMixin
from datetime import datetime, timezone

class Usuario(db.Model, UserMixin):
    __tablename__ = 'usuario'
    id_usuario       = db.Column(db.Integer, primary_key=True)
    tipo_documento   = db.Column(db.String(20))
    numero_documento = db.Column(db.String(30))
    nombres          = db.Column(db.String(100), nullable=False)
    apellidos        = db.Column(db.String(100), nullable=False)
    correo           = db.Column(db.String(100), unique=True, nullable=False)
    telefono         = db.Column(db.String(20))
    password_hash    = db.Column(db.String(255), nullable=False)
    estado           = db.Column(db.Boolean, default=True)
    fecha_creacion   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relaciones
    roles            = db.relationship('UsuarioRol', back_populates='usuario')
    instructor       = db.relationship('Instructor', back_populates='usuario', uselist=False)
    aprendiz         = db.relationship('Aprendiz', back_populates='usuario', uselist=False)
    historial        = db.relationship('HistorialCambios', back_populates='usuario')
    notificaciones   = db.relationship('Notificacion', back_populates='usuario')

    def get_id(self):
        return str(self.id_usuario)