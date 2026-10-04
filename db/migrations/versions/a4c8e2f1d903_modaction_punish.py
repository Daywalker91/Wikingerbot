"""modlog.action: punish/unpunish (Strafrolle)

Revision ID: a4c8e2f1d903
Revises: f3a9c1d7e2b6
Create Date: 2026-10-04 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4c8e2f1d903'
down_revision: Union[str, None] = 'f3a9c1d7e2b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = ('kick', 'ban', 'unban', 'warn', 'mute', 'unmute', 'timeout')
NEW = OLD + ('punish', 'unpunish')


def upgrade() -> None:
    with op.batch_alter_table('modlog') as batch:
        batch.alter_column('action', existing_type=sa.Enum(*OLD, name='modaction'),
                           type_=sa.Enum(*NEW, name='modaction'), existing_nullable=False)


def downgrade() -> None:
    op.execute("DELETE FROM modlog WHERE action IN ('punish', 'unpunish')")
    with op.batch_alter_table('modlog') as batch:
        batch.alter_column('action', existing_type=sa.Enum(*NEW, name='modaction'),
                           type_=sa.Enum(*OLD, name='modaction'), existing_nullable=False)
