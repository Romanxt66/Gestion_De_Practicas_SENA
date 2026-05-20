from app import db

class Aprendiz(db.Model):
    __tablename__ = 'aprendiz'
    id_aprendiz      = db.Column(db.Integer, primary_key=True)
    id_usuario       = db.Column(db.Integer, db.ForeignKey('usuario.id_usuario'), unique=True, nullable=False)
    id_empresa       = db.Column(db.Integer, db.ForeignKey('empresa.id_empresa'), nullable=True)
    ficha            = db.Column(db.String(30))
    estado_practica  = db.Column(db.String(30), default='En proceso')
    horas_requeridas = db.Column(db.Integer, default=0)
    horas_cumplidas  = db.Column(db.Integer, default=0)

    usuario          = db.relationship('Usuario', back_populates='aprendiz')
    empresa          = db.relationship('Empresa', backref='aprendices')
    cursos           = db.relationship('CursoAprendiz', back_populates='aprendiz')
    evidencias       = db.relationship('Evidencia', back_populates='aprendiz')
    progreso         = db.relationship('ProgresoAprendiz', back_populates='aprendiz')
    backup           = db.relationship('AprendizBackup', back_populates='aprendiz', uselist=False)