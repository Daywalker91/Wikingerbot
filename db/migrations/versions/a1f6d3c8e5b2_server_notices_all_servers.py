"""server_notices.server_id optional: Ankuendigung fuer alle Server (AMP selbst)

Revision ID: a1f6d3c8e5b2
Revises: e4a7c2b9d1f3
Create Date: 2026-10-20 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f6d3c8e5b2'
down_revision: Union[str, None] = 'e4a7c2b9d1f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('server_notices') as batch:
        batch.alter_column('server_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM server_notices WHERE server_id IS NULL")
    with op.batch_alter_table('server_notices') as batch:
        batch.alter_column('server_id', existing_type=sa.Integer(), nullable=False)
