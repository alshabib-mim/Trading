"""Alerts layer: alert_config table (Telegram, encrypted creds + per-event
toggles, ships disabled) and risk_state.halt_alerted (breaker edge-trigger).

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-06-01

"""
import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b4c5d6e7f8a9'
down_revision: Union[str, Sequence[str], None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    now = datetime.datetime.utcnow()

    op.create_table(
        'alert_config',
        sa.Column('id', sa.Integer, primary_key=True, index=True),
        sa.Column('channel', sa.String),
        sa.Column('enabled', sa.Boolean),
        sa.Column('bot_token_encrypted', sa.String, nullable=True),
        sa.Column('chat_id_encrypted', sa.String, nullable=True),
        sa.Column('events', sa.JSON),
        sa.Column('updated_at', sa.DateTime),
    )

    # Seed the single config row: Telegram, disabled (no spend / no sends until the
    # owner adds the token + chat id and flips it on), all event types on by default.
    alert_config = sa.table(
        'alert_config',
        sa.column('channel', sa.String), sa.column('enabled', sa.Boolean),
        sa.column('bot_token_encrypted', sa.String), sa.column('chat_id_encrypted', sa.String),
        sa.column('events', sa.JSON), sa.column('updated_at', sa.DateTime),
    )
    op.bulk_insert(alert_config, [{
        'channel': 'telegram', 'enabled': False,
        'bot_token_encrypted': None, 'chat_id_encrypted': None,
        'events': {
            'signal_armed': True, 'position_opened': True,
            'exit_hit': True, 'breaker': True,
        },
        'updated_at': now,
    }])

    # Breaker edge-trigger memory: signature of the last halt episode alerted.
    op.add_column('risk_state', sa.Column('halt_alerted', sa.String, nullable=True))


def downgrade() -> None:
    op.drop_column('risk_state', 'halt_alerted')
    op.drop_table('alert_config')
