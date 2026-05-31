"""Forex macro news (4th signal source): macro_bias snapshot table, 'macro'
source_config row (Claude web_search, no key needed — uses ANTHROPIC_API_KEY),
and trading_signals.news_conf flag.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-06-01

"""
import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, Sequence[str], None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    now = datetime.datetime.utcnow()

    # 1. Per-currency macro bias snapshots (one row per refresh).
    op.create_table(
        'macro_bias',
        sa.Column('id', sa.Integer, primary_key=True, index=True),
        sa.Column('currencies', sa.JSON),
        sa.Column('gold', sa.JSON, nullable=True),
        sa.Column('model', sa.String, nullable=True),
        sa.Column('raw', sa.String, nullable=True),
        sa.Column('timestamp', sa.DateTime, index=True),
    )

    # 2. The 'macro' source row. Forex-only, confirm-only. No credential —
    #    it uses the server's ANTHROPIC_API_KEY via Claude web_search. Disabled
    #    by default; owner flips it on in Config. Refresh every 4h (interval),
    #    snapshot good for 12h (freshness) to tolerate one missed run.
    source_config = sa.table(
        'source_config',
        sa.column('source', sa.String), sa.column('provider', sa.String),
        sa.column('credentials_encrypted', sa.String), sa.column('enabled', sa.Boolean),
        sa.column('weight', sa.Float), sa.column('freshness_seconds', sa.Integer),
        sa.column('interval_seconds', sa.Integer), sa.column('options', sa.JSON),
        sa.column('updated_at', sa.DateTime),
    )
    #    Schedule lives in options (UI-tunable, no redeploy): run_times = UTC
    #    HH:MM list (1 = once/day default, 2 = twice/day); skip_forex_weekend skips
    #    the Fri 22:00 → Sun 22:00 UTC forex weekend. freshness 80h BRIDGES that
    #    weekend (no weekend macro releases) so Friday's read stays applied through
    #    Monday. interval_seconds is just the scheduler tick cadence.
    op.bulk_insert(source_config, [{
        'source': 'macro', 'provider': 'claude_websearch', 'credentials_encrypted': None,
        'enabled': False, 'weight': 1.0, 'freshness_seconds': 288000, 'interval_seconds': 900,
        'options': {
            'model': 'claude-sonnet-4-6',
            'currencies': ['USD', 'EUR', 'JPY', 'GBP', 'CHF', 'AUD'],
            'max_uses': 12,
            'run_times': ['13:00'],        # UTC; 1 entry = once/day, 2 = twice/day
            'skip_forex_weekend': True,    # skip Fri 22:00 → Sun 22:00 UTC
        },
        'updated_at': now,
    }])

    # 3. news_conf flag on signals (forex-only; null elsewhere).
    op.add_column('trading_signals', sa.Column('news_conf', sa.Boolean, nullable=True))


def downgrade() -> None:
    op.drop_column('trading_signals', 'news_conf')
    source_config = sa.table('source_config', sa.column('source', sa.String))
    op.execute(source_config.delete().where(source_config.c.source == 'macro'))
    op.drop_table('macro_bias')
