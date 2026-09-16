from datetime import datetime, timezone

from app import db


class InstructorAprendiz(db.Model):
    """Asignación directa de un aprendiz a un instructor.

    El camino normal es por ficha: el instructor está a cargo de una ficha y
    con ella de todos sus aprendices. Esta tabla cubre los casos sueltos —un
    aprendiz que sigue otro instructor, o alguien que acompaña solo a parte de
    la ficha— sin tener que inventar una ficha nueva.

    Las dos vías suman: un aprendiz puede llegar por ficha, por asignación
    directa, o por las dos.
    """
    __tablename__ = 'instructor_aprendiz'

    id_instructor = db.Column(db.Integer, db.ForeignKey('instructor.id_instructor'),
                              primary_key=True)
    id_aprendiz   = db.Column(db.Integer, db.ForeignKey('aprendiz.id_aprendiz'),
                              primary_key=True)
    fecha_asignacion = db.Column(db.DateTime,
                                 default=lambda: datetime.now(timezone.utc))

    instructor = db.relationship('Instructor', backref='aprendices_directos')
    aprendiz   = db.relationship('Aprendiz', backref='instructores_directos')
