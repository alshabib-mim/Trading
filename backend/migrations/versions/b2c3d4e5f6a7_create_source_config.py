"""Create source_config and seed the four sources

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-31

"""
import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'source_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('credentials_encrypted', sa.String(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('weight', sa.Float(), nullable=True),
        sa.Column('freshness_seconds', sa.Integer(), nullable=True),
        sa.Column('interval_seconds', sa.Integer(), nullable=True),
        sa.Column('options', sa.JSON(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_source_config_id'), 'source_config', ['id'], unique=False)
    op.create_index(op.f('ix_source_config_source'), 'source_config', ['source'], unique=True)

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
    now = datetime.datetime.utcnow()
    op.bulk_insert(source_config, [
        {
            'source': 'technical', 'provider': 'kraken', 'credentials_encrypted': None,
            'enabled': True, 'weight': 1.0, 'freshness_seconds': 3600, 'interval_seconds': 900,
            'options': {'timeframe': '1h', 'limit': 300}, 'updated_at': now,
        },
        {
            'source': 'whale', 'provider': 'whale_alert', 'credentials_encrypted': None,
            'enabled': False, 'weight': 1.0, 'freshness_seconds': 3600, 'interval_seconds': 900,
            'options': None, 'updated_at': now,
        },
        {
            'source': 'institutional', 'provider': 'sec_api', 'credentials_encrypted': None,
            'enabled': False, 'weight': 1.0, 'freshness_seconds': 7776000, 'interval_seconds': 86400,
            'options': None, 'updated_at': now,
        },
        {
            'source': 'sentiment', 'provider': 'claude', 'credentials_encrypted': None,
            'enabled': False, 'weight': 1.0, 'freshness_seconds': 86400, 'interval_seconds': 3600,
            'options': None, 'updated_at': now,
        },
    ])


def downgrade() -> None:
    op.drop_index(op.f('ix_source_config_source'), table_name='source_config')
    op.drop_index(op.f('ix_source_config_id'), table_name='source_config')
    op.drop_table('source_config')
