from datetime import datetime, timezone

from app import db


class VerificacionCorreo(db.Model):
    """Un alta que todavía no es una cuenta.

    Mientras el correo no se confirma, los datos viven aquí y NO en la tabla
    de usuarios: así una dirección inventada nunca llega a ocupar un correo ni
    un número de documento reales.

    Los datos del formulario se guardan serializados porque son transitorios y
    cambian según el rol (una ficha para el aprendiz, un área para el
    instructor). La contraseña se guarda ya cifrada, nunca en claro.
    """
    __tablename__ = 'verificacion_correo'

    id_verificacion = db.Column(db.Integer, primary_key=True)
    correo          = db.Column(db.String(100), nullable=False, index=True)
    datos           = db.Column(db.Text, nullable=False)
    # 'registro' (se registró la persona) o 'admin' (lo creó un administrador)
    origen          = db.Column(db.String(20), nullable=False, default='registro')
    id_creador      = db.Column(db.Integer, db.ForeignKey('usuario.id_usuario'),
                                nullable=True)
    fecha_creacion  = db.Column(db.DateTime,
                                default=lambda: datetime.now(timezone.utc))

    creador = db.relationship('Usuario', foreign_keys=[id_creador])
