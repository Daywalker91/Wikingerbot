"""add community_posts

Revision ID: d7a3f1c2e8b4
Revises: c4d1e7a9b2f3
Create Date: 2026-10-02 19:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7a3f1c2e8b4'
down_revision: Union[str, None] = 'c4d1e7a9b2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('community_posts',
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('item_id', sa.BigInteger(), nullable=False),
    sa.Column('guild_id', sa.BigInteger(), nullable=False),
    sa.Column('channel_id', sa.BigInteger(), nullable=False),
    sa.Column('message_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['guild_id'], ['guilds.id'], ),
    sa.PrimaryKeyConstraint('kind', 'item_id', 'guild_id')
    )


def downgrade() -> None:
    op.drop_table('community_posts')
