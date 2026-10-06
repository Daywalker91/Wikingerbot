"""server_notices: angekuendigte Neustarts und Wartungen (servernews-Cog)

Revision ID: d8f3b2a6c1e4
Revises: c5e1a7d3b9f2
Create Date: 2026-10-06 21:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8f3b2a6c1e4'
down_revision: Union[str, None] = 'c5e1a7d3b9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'server_notices',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('guild_id', sa.BigInteger(), sa.ForeignKey('guilds.id'), nullable=False),
        sa.Column('server_id', sa.Integer(), sa.ForeignKey('servers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('origin', sa.String(10), nullable=False, server_default='manual'),
        sa.Column('kind', sa.String(12), nullable=False, server_default='restart'),
        sa.Column('at', sa.DateTime(), nullable=False),
        sa.Column('duration_min', sa.Integer(), nullable=True),
        sa.Column('reason', sa.String(200), nullable=True),
        sa.Column('created_by', sa.BigInteger(), nullable=True),
        sa.Column('status', sa.String(10), nullable=False, server_default='pending'),
        sa.Column('sent_leads', sa.Text(), nullable=False),
        sa.Column('amp_key', sa.String(80), nullable=True, unique=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_server_notices_open', 'server_notices', ['status', 'at'])


def downgrade() -> None:
    op.drop_index('ix_server_notices_open', table_name='server_notices')
    op.drop_table('server_notices')
