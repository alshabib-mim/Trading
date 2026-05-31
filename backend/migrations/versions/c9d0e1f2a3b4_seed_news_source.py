"""Seed the 'news' source (Finnhub) for the sentiment headline feed

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-05-31

"""
import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


source_config = sa.table(
    'source_config',
    sa.column('source', sa.String),
    sa.column('provider', sa.String),
    sa.column('credentials_encrypted', sa.String),
    sa.column('enabled', sa.Boolean),
    sa.column('weight', sa.Float),
    sa.column('freshness_seconds', sa.Integer),
    sa.column('interval_seconds', sa.Integer),
    sa.column('options', sa.JSON),
    sa.column('updated_at', sa.DateTime),
)


def upgrade() -> None:
    op.bulk_insert(source_config, [
        {
            'source': 'news', 'provider': 'finnhub', 'credentials_encrypted': None,
            'enabled': False, 'weight': 1.0,
            'freshness_seconds': 86400,   # headlines stay relevant ~1 day
            'interval_seconds': 3600,     # hourly — conservative for the free tier
            'options': {'lookback_days': 2, 'max_headlines': 15},
            'updated_at': datetime.datetime.utcnow(),
        },
    ])


def downgrade() -> None:
    op.execute(source_config.delete().where(source_config.c.source == 'news'))
