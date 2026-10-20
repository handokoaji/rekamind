"""summary.key_points: the few things worth remembering from a meeting (apart from decisions and the timeline)

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('summaries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('key_points', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    with op.batch_alter_table('summaries', schema=None) as batch_op:
        batch_op.drop_column('key_points')
