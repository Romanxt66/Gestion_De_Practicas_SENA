from app import db
from datetime import datetime, timezone


class CuentaGoogle(db.Model):
    """Cuenta de Google vinculada por un usuario para enviar sus notificaciones.

    Guarda el refresh token (cifrado) que Google entrega al autorizar. El access
    token se pide cuando hace falta y no se persiste: dura una hora y es más
    seguro no tenerlo en la base.
    """
    __tablename__ = 'cuenta_google'

    id_cuenta       = db.Column(db.Integer, primary_key=True)
    id_usuario      = db.Column(db.Integer, db.ForeignKey('usuario.id_usuario'),
                                unique=True, nullable=False)
    correo_google   = db.Column(db.String(150), nullable=False)
    # Cifrado con Fernet; nunca se muestra ni se registra en logs.
    refresh_token   = db.Column(db.Text, nullable=False)
    scopes          = db.Column(db.Text)
    fecha_conexion  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    ultimo_error    = db.Column(db.Text)

    usuario         = db.relationship('Usuario', back_populates='cuenta_google')
