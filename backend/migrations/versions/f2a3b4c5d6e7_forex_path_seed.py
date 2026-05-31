"""Forex/gold path: Twelve Data source, per-type stops, seed forex assets

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-06-01

"""
import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FOREX = ["EUR-USD", "GBP-USD", "USD-JPY", "XAU-USD"]


def upgrade() -> None:
    now = datetime.datetime.utcnow()

    # 1. Twelve Data provider row (owner adds the key in Config, encrypted).
    source_config = sa.table(
        'source_config',
        sa.column('source', sa.String), sa.column('provider', sa.String),
        sa.column('credentials_encrypted', sa.String), sa.column('enabled', sa.Boolean),
        sa.column('weight', sa.Float), sa.column('freshness_seconds', sa.Integer),
        sa.column('interval_seconds', sa.Integer), sa.column('options', sa.JSON),
        sa.column('updated_at', sa.DateTime),
    )
    op.bulk_insert(source_config, [{
        'source': 'forex', 'provider': 'twelvedata', 'credentials_encrypted': None,
        'enabled': False, 'weight': 1.0, 'freshness_seconds': 3600, 'interval_seconds': 900,
        'options': {'outputsize': 300}, 'updated_at': now,
    }])

    # 2. Per-asset-type stops: forex 1.0%, gold 2.5% (by_symbol override);
    #    stock/crypto keep the 6.0% default. Take-profit RR stays global.
    risk_config = sa.table(
        'risk_config',
        sa.column('key', sa.String), sa.column('params', sa.JSON), sa.column('updated_at', sa.DateTime),
    )
    op.execute(
        risk_config.update().where(risk_config.c.key == 'stop_loss').values(
            params={
                "pct": 6.0,
                "by_type": {"forex": 1.0},
                "by_symbol": {"XAU-USD": 2.5},
            },
            updated_at=now,
        )
    )

    # 3. Seed the forex universe (3 majors + gold), enabled.
    asset_config = sa.table(
        'asset_config',
        sa.column('symbol', sa.String), sa.column('asset_type', sa.String),
        sa.column('enabled', sa.Boolean), sa.column('updated_at', sa.DateTime),
    )
    op.bulk_insert(asset_config, [
        {'symbol': s, 'asset_type': 'forex', 'enabled': True, 'updated_at': now} for s in FOREX
    ])


def downgrade() -> None:
    now = datetime.datetime.utcnow()
    asset_config = sa.table('asset_config', sa.column('symbol', sa.String))
    op.execute(asset_config.delete().where(asset_config.c.symbol.in_(FOREX)))
    risk_config = sa.table('risk_config', sa.column('key', sa.String), sa.column('params', sa.JSON), sa.column('updated_at', sa.DateTime))
    op.execute(risk_config.update().where(risk_config.c.key == 'stop_loss').values(params={"pct": 6.0}, updated_at=now))
    source_config = sa.table('source_config', sa.column('source', sa.String))
    op.execute(source_config.delete().where(source_config.c.source == 'forex'))
