from app import db

class CursoInstructor(db.Model):
    __tablename__ = 'curso_instructor'
    id_curso      = db.Column(db.Integer, db.ForeignKey('curso.id_curso'), primary_key=True)
    id_instructor = db.Column(db.Integer, db.ForeignKey('instructor.id_instructor'), primary_key=True)

    curso         = db.relationship('Curso', back_populates='instructores')
    instructor    = db.relationship('Instructor', back_populates='cursos')