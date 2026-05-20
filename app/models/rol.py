from app import db

class Rol(db.Model):
    __tablename__ = 'rol'
    id_rol      = db.Column(db.Integer, primary_key=True)
    nombre      = db.Column(db.String(50), nullable=False)
    descripcion = db.Column(db.Text)

    usuarios    = db.relationship('UsuarioRol', back_populates='rol')