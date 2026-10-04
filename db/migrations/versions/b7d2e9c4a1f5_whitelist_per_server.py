"""servers.whitelist_enabled, whitelist_requests.status 'revoked'

Revision ID: b7d2e9c4a1f5
Revises: a4c8e2f1d903
Create Date: 2026-10-04 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d2e9c4a1f5'
down_revision: Union[str, None] = 'a4c8e2f1d903'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = ('pending', 'approved', 'denied')
NEW = OLD + ('revoked',)


def upgrade() -> None:
    # Whitelist pro Server an/aus: an = Zugang (Discord-Rolle) nur nach Freigabe
    with op.batch_alter_table('servers') as batch:
        batch.add_column(sa.Column('whitelist_enabled', sa.Boolean(), server_default=sa.false(), nullable=False))
    # Freigabe wieder entzogen (/whitelist entziehen)
    with op.batch_alter_table('whitelist_requests') as batch:
        batch.alter_column('status', existing_type=sa.Enum(*OLD, name='whiteliststatus'),
                           type_=sa.Enum(*NEW, name='whiteliststatus'), existing_nullable=False)


def downgrade() -> None:
    op.execute("UPDATE whitelist_requests SET status = 'denied' WHERE status = 'revoked'")
    with op.batch_alter_table('whitelist_requests') as batch:
        batch.alter_column('status', existing_type=sa.Enum(*NEW, name='whiteliststatus'),
                           type_=sa.Enum(*OLD, name='whiteliststatus'), existing_nullable=False)
    with op.batch_alter_table('servers') as batch:
        batch.drop_column('whitelist_enabled')
