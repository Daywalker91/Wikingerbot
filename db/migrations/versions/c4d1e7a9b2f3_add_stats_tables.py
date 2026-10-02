"""add stats tables

Revision ID: c4d1e7a9b2f3
Revises: f0224706c1c0
Create Date: 2026-10-02 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d1e7a9b2f3'
down_revision: Union[str, None] = 'f0224706c1c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('stats_daily',
    sa.Column('guild_id', sa.BigInteger(), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('joins', sa.Integer(), nullable=False),
    sa.Column('leaves', sa.Integer(), nullable=False),
    sa.Column('messages', sa.Integer(), nullable=False),
    sa.Column('voice_seconds', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['guild_id'], ['guilds.id'], ),
    sa.PrimaryKeyConstraint('guild_id', 'day')
    )
    op.create_table('stats_member_daily',
    sa.Column('guild_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('messages', sa.Integer(), nullable=False),
    sa.Column('voice_seconds', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['guild_id'], ['guilds.id'], ),
    sa.PrimaryKeyConstraint('guild_id', 'user_id', 'day')
    )


def downgrade() -> None:
    op.drop_table('stats_member_daily')
    op.drop_table('stats_daily')
