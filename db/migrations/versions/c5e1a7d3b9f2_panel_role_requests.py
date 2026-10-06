"""panel_role_requests: Selbstwahl-Rollen mit Bestaetigung

Revision ID: c5e1a7d3b9f2
Revises: b7d2e9c4a1f5
Create Date: 2026-10-06 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5e1a7d3b9f2'
down_revision: Union[str, None] = 'b7d2e9c4a1f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'panel_role_requests',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('guild_id', sa.BigInteger(), sa.ForeignKey('guilds.id'), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('role_id', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(10), nullable=False, server_default='pending'),
        sa.Column('decided_by', sa.BigInteger(), nullable=True),
        sa.Column('note', sa.String(255), nullable=True),
        sa.Column('channel_id', sa.BigInteger(), nullable=True),
        sa.Column('message_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_panel_role_requests_member', 'panel_role_requests', ['guild_id', 'user_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_panel_role_requests_member', table_name='panel_role_requests')
    op.drop_table('panel_role_requests')
