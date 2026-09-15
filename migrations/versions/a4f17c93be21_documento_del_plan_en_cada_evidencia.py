"""documento del plan en cada evidencia

Revision ID: a4f17c93be21
Revises: 6528cbb50efe
Create Date: 2026-09-14

Cada evidencia pasa a declarar qué documento del plan de etapa productiva es
(bitácora, acta o formato de planeación de seguimiento). Las evidencias que ya
estaban subidas quedan en NULL y la vista las muestra como "sin clasificar".
"""
from alembic import op
import sqlalchemy as sa

revision = 'a4f17c93be21'
down_revision = '6528cbb50efe'
branch_labels = None
depends_on = None


def upgrade():
    columnas = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('evidencia')}
    if 'documento' in columnas:
        return
    with op.batch_alter_table('evidencia', schema=None) as batch_op:
        batch_op.add_column(sa.Column('documento', sa.String(length=25), nullable=True))
        batch_op.create_index('ix_evidencia_documento', ['documento'], unique=False)


def downgrade():
    with op.batch_alter_table('evidencia', schema=None) as batch_op:
        batch_op.drop_index('ix_evidencia_documento')
        batch_op.drop_column('documento')
