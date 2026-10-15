"""integrations and task links

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('integrations',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('owner_id', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.Column('secret_enc', sa.Text(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_integrations_owner_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_integrations'))
    )
    op.create_index(op.f('ix_integrations_owner_id'), 'integrations', ['owner_id'], unique=False)
    op.create_table('task_links',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('task_id', sa.String(), nullable=False),
    sa.Column('integration_id', sa.String(), nullable=False),
    sa.Column('external_id', sa.String(), nullable=True),
    sa.Column('external_url', sa.String(), nullable=True),
    sa.Column('payload_hash', sa.String(), nullable=True),
    sa.Column('state', sa.String(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('pushed_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['integration_id'], ['integrations.id'], name=op.f('fk_task_links_integration_id_integrations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], name=op.f('fk_task_links_task_id_tasks'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_task_links')),
    sa.UniqueConstraint('task_id', 'integration_id', name='uq_task_links_task_integration')
    )
    op.create_index(op.f('ix_task_links_integration_id'), 'task_links', ['integration_id'], unique=False)
    op.create_index(op.f('ix_task_links_task_id'), 'task_links', ['task_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_task_links_task_id'), table_name='task_links')
    op.drop_index(op.f('ix_task_links_integration_id'), table_name='task_links')
    op.drop_table('task_links')
    op.drop_index(op.f('ix_integrations_owner_id'), table_name='integrations')
    op.drop_table('integrations')
