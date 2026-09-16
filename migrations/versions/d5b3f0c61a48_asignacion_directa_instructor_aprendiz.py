"""asignación directa instructor-aprendiz

Revision ID: d5b3f0c61a48
Revises: c8e4a1d7b902
Create Date: 2026-09-16

Hasta ahora un instructor solo llegaba a un aprendiz a través de la ficha.
Esta tabla permite además asignarle aprendices sueltos, sin inventar fichas.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd5b3f0c61a48'
down_revision = 'c8e4a1d7b902'
branch_labels = None
depends_on = None


def upgrade():
    if 'instructor_aprendiz' in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        'instructor_aprendiz',
        sa.Column('id_instructor', sa.Integer(), nullable=False),
        sa.Column('id_aprendiz', sa.Integer(), nullable=False),
        sa.Column('fecha_asignacion', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['id_instructor'], ['instructor.id_instructor'], ),
        sa.ForeignKeyConstraint(['id_aprendiz'], ['aprendiz.id_aprendiz'], ),
        sa.PrimaryKeyConstraint('id_instructor', 'id_aprendiz'),
    )


def downgrade():
    op.drop_table('instructor_aprendiz')
