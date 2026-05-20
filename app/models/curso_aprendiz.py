from app import db

class CursoAprendiz(db.Model):
    __tablename__ = 'curso_aprendiz'
    id_curso    = db.Column(db.Integer, db.ForeignKey('curso.id_curso'), primary_key=True)
    id_aprendiz = db.Column(db.Integer, db.ForeignKey('aprendiz.id_aprendiz'), primary_key=True)
    estado      = db.Column(db.String(30))

    curso       = db.relationship('Curso', back_populates='aprendices')
    aprendiz    = db.relationship('Aprendiz', back_populates='cursos')