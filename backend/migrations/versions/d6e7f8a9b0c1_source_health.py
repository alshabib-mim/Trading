"""Per-source health: source_health table (last-run outcome, separate from data writes).

The new 'source_error' alert event needs no data migration — alerts._emit defaults
it to True (events.get(event, True)) and the Config UI renders it from EVENT_TYPES.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-06-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd6e7f8a9b0c1'
down_revision: Union[str, Sequence[str], None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'source_health',
        sa.Column('id', sa.Integer, primary_key=True, index=True),
        sa.Column('source', sa.String, unique=True, index=True),
        sa.Column('last_run_at', sa.DateTime, nullable=True),
        sa.Column('last_state', sa.String, nullable=True),
        sa.Column('last_message', sa.String, nullable=True),
        sa.Column('last_ok_at', sa.DateTime, nullable=True),
        sa.Column('failing_since', sa.DateTime, nullable=True),
        sa.Column('alerted', sa.Boolean),
        sa.Column('updated_at', sa.DateTime),
    )


def downgrade() -> None:
    op.drop_table('source_health')
