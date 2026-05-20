from app import db

class Instructor(db.Model):
    __tablename__ = 'instructor'
    id_instructor  = db.Column(db.Integer, primary_key=True)
    id_usuario     = db.Column(db.Integer, db.ForeignKey('usuario.id_usuario'), unique=True, nullable=False)
    area_formacion = db.Column(db.String(100))
    activo         = db.Column(db.Boolean, default=True)

    usuario        = db.relationship('Usuario', back_populates='instructor')
    cursos         = db.relationship('CursoInstructor', back_populates='instructor')