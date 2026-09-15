"""verificación de correo antes del alta

Revision ID: c8e4a1d7b902
Revises: a4f17c93be21
Create Date: 2026-09-15

Las altas quedan en espera hasta que la persona confirma su correo. Mientras
tanto no existe usuario, así que un correo inventado no bloquea una dirección
ni un número de documento reales.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c8e4a1d7b902'
down_revision = 'a4f17c93be21'
branch_labels = None
depends_on = None


def upgrade():
    if 'verificacion_correo' in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        'verificacion_correo',
        sa.Column('id_verificacion', sa.Integer(), nullable=False),
        sa.Column('correo', sa.String(length=100), nullable=False),
        sa.Column('datos', sa.Text(), nullable=False),
        sa.Column('origen', sa.String(length=20), nullable=False),
        sa.Column('id_creador', sa.Integer(), nullable=True),
        sa.Column('fecha_creacion', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['id_creador'], ['usuario.id_usuario'], ),
        sa.PrimaryKeyConstraint('id_verificacion'),
    )
    op.create_index('ix_verificacion_correo_correo', 'verificacion_correo',
                    ['correo'], unique=False)


def downgrade():
    op.drop_index('ix_verificacion_correo_correo', table_name='verificacion_correo')
    op.drop_table('verificacion_correo')
