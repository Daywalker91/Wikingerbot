"""add servers.banner_steam_art

Revision ID: f3a9c1d7e2b6
Revises: e8b5c3d4f9a1
Create Date: 2026-10-03 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a9c1d7e2b6'
down_revision: Union[str, None] = 'e8b5c3d4f9a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Steam-Artwork als Banner-Hintergrund abschaltbar (sonst gewinnt es immer vor Theme/Farben)
    with op.batch_alter_table('servers') as batch:
        batch.add_column(sa.Column('banner_steam_art', sa.Boolean(), server_default=sa.true(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('servers') as batch:
        batch.drop_column('banner_steam_art')
