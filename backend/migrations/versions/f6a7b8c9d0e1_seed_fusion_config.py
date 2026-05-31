"""Seed the fusion config row (arm_threshold + weights, tunable in the UI)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-31

"""
import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
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
            'source': 'fusion', 'provider': 'builtin', 'credentials_encrypted': None,
            'enabled': True, 'weight': 1.0, 'freshness_seconds': None,
            'interval_seconds': 900,
            'options': {
                "arm_threshold": 0.6,
                "w_direction": 0.6,
                "w_sentiment": 0.15,
                "w_support": 0.1,
            },
            'updated_at': datetime.datetime.utcnow(),
        },
    ])


def downgrade() -> None:
    op.execute(source_config.delete().where(source_config.c.source == 'fusion'))
