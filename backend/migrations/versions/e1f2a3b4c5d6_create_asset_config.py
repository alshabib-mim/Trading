"""Create asset_config and seed the universe (8 stocks + 3 crypto)

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-05-31

"""
import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STOCKS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "OXY"]
CRYPTO = ["BTC-USD", "ETH-USD", "SOL-USD"]


def upgrade() -> None:
    op.create_table(
        'asset_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('asset_type', sa.String(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_asset_config_id'), 'asset_config', ['id'], unique=False)
    op.create_index(op.f('ix_asset_config_symbol'), 'asset_config', ['symbol'], unique=True)

    asset_config = sa.table(
        'asset_config',
        sa.column('symbol', sa.String),
        sa.column('asset_type', sa.String),
        sa.column('enabled', sa.Boolean),
        sa.column('updated_at', sa.DateTime),
    )
    now = datetime.datetime.utcnow()
    rows = (
        [{'symbol': s, 'asset_type': 'stock', 'enabled': True, 'updated_at': now} for s in STOCKS]
        + [{'symbol': s, 'asset_type': 'crypto', 'enabled': True, 'updated_at': now} for s in CRYPTO]
    )
    op.bulk_insert(asset_config, rows)


def downgrade() -> None:
    op.drop_index(op.f('ix_asset_config_symbol'), table_name='asset_config')
    op.drop_index(op.f('ix_asset_config_id'), table_name='asset_config')
    op.drop_table('asset_config')
