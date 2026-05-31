"""Add direction and reasoning to trading_signals

Revision ID: a1b2c3d4e5f6
Revises: 4fd106201b07
Create Date: 2026-05-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '4fd106201b07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('trading_signals', sa.Column('direction', sa.String(), nullable=True))
    op.add_column('trading_signals', sa.Column('reasoning', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('trading_signals', 'reasoning')
    op.drop_column('trading_signals', 'direction')
