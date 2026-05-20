from app import db

class Curso(db.Model):
    __tablename__ = 'curso'
    id_curso     = db.Column(db.Integer, primary_key=True)
    nombre       = db.Column(db.String(150), nullable=False)
    ficha        = db.Column(db.String(30))
    fecha_inicio = db.Column(db.Date)
    fecha_fin    = db.Column(db.Date)

    instructores = db.relationship('CursoInstructor', back_populates='curso')
    aprendices   = db.relationship('CursoAprendiz', back_populates='curso')
    progreso     = db.relationship('ProgresoAprendiz', back_populates='curso')