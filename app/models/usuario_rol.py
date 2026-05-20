from app import db

class UsuarioRol(db.Model):
    __tablename__ = 'usuario_rol'
    id_usuario = db.Column(db.Integer, db.ForeignKey('usuario.id_usuario'), primary_key=True)
    id_rol     = db.Column(db.Integer, db.ForeignKey('rol.id_rol'), primary_key=True)

    usuario    = db.relationship('Usuario', back_populates='roles')
    rol        = db.relationship('Rol', back_populates='usuarios')