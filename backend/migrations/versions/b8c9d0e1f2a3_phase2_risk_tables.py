"""Phase 2: risk_config + risk_state tables, executed_trades risk columns

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-05-31

"""
import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STARTING_CAPITAL = 100000.0


def upgrade() -> None:
    # --- executed_trades: paper-execution columns ---
    op.add_column('executed_trades', sa.Column('side', sa.String(), nullable=True))
    op.add_column('executed_trades', sa.Column('close_reason', sa.String(), nullable=True))
    op.add_column('executed_trades', sa.Column('overrides', sa.JSON(), nullable=True))

    # --- risk_config (owner-editable) ---
    op.create_table(
        'risk_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('params', sa.JSON(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_risk_config_id'), 'risk_config', ['id'], unique=False)
    op.create_index(op.f('ix_risk_config_key'), 'risk_config', ['key'], unique=True)

    risk_config = sa.table(
        'risk_config',
        sa.column('key', sa.String),
        sa.column('enabled', sa.Boolean),
        sa.column('params', sa.JSON),
        sa.column('updated_at', sa.DateTime),
    )
    now = datetime.datetime.utcnow()
    op.bulk_insert(risk_config, [
        {'key': 'account', 'enabled': True, 'params': {'starting_capital': STARTING_CAPITAL, 'risk_per_trade_pct': 1.0, 'max_position_pct': 5.0}, 'updated_at': now},
        {'key': 'daily_loss', 'enabled': True, 'params': {'limit_pct': 2.0}, 'updated_at': now},
        {'key': 'drawdown', 'enabled': True, 'params': {'limit_pct': 10.0}, 'updated_at': now},
        {'key': 'max_concurrent', 'enabled': True, 'params': {'max': 5}, 'updated_at': now},
        {'key': 'stop_loss', 'enabled': True, 'params': {'pct': 6.0}, 'updated_at': now},
        {'key': 'take_profit', 'enabled': True, 'params': {'rr': 2.5}, 'updated_at': now},
    ])

    # --- risk_state (engine-written, singleton) ---
    op.create_table(
        'risk_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('peak_equity', sa.Float(), nullable=True),
        sa.Column('day_date', sa.String(), nullable=True),
        sa.Column('day_start_equity', sa.Float(), nullable=True),
        sa.Column('manual_halt', sa.Boolean(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_risk_state_id'), 'risk_state', ['id'], unique=False)
    risk_state = sa.table(
        'risk_state',
        sa.column('peak_equity', sa.Float),
        sa.column('day_date', sa.String),
        sa.column('day_start_equity', sa.Float),
        sa.column('manual_halt', sa.Boolean),
        sa.column('updated_at', sa.DateTime),
    )
    op.bulk_insert(risk_state, [
        {'peak_equity': STARTING_CAPITAL, 'day_date': None, 'day_start_equity': STARTING_CAPITAL, 'manual_halt': False, 'updated_at': now},
    ])


def downgrade() -> None:
    op.drop_index(op.f('ix_risk_state_id'), table_name='risk_state')
    op.drop_table('risk_state')
    op.drop_index(op.f('ix_risk_config_key'), table_name='risk_config')
    op.drop_index(op.f('ix_risk_config_id'), table_name='risk_config')
    op.drop_table('risk_config')
    op.drop_column('executed_trades', 'overrides')
    op.drop_column('executed_trades', 'close_reason')
    op.drop_column('executed_trades', 'side')
