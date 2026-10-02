"""add amp_accounts

Revision ID: e8b5c3d4f9a1
Revises: d7a3f1c2e8b4
Create Date: 2026-10-02 23:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8b5c3d4f9a1'
down_revision: Union[str, None] = 'd7a3f1c2e8b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('amp_accounts',
    sa.Column('site_user_id', sa.Integer(), nullable=False),
    sa.Column('amp_user_id', sa.String(length=64), nullable=False),
    sa.Column('amp_username', sa.String(length=64), nullable=False),
    sa.Column('disabled', sa.Boolean(), nullable=False),
    sa.Column('role_ids', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('site_user_id')
    )


def downgrade() -> None:
    op.drop_table('amp_accounts')
