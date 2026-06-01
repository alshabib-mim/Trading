"""Chat assistant action audit/lifecycle table (chat_action).

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-06-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5d6e7f8a9b0'
down_revision: Union[str, Sequence[str], None] = 'b4c5d6e7f8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chat_action',
        sa.Column('id', sa.Integer, primary_key=True, index=True),
        sa.Column('action_id', sa.String, unique=True, index=True),
        sa.Column('username', sa.String, index=True),
        sa.Column('target', sa.String),
        sa.Column('label', sa.String, nullable=True),
        sa.Column('before_value', sa.String, nullable=True),
        sa.Column('after_value', sa.String, nullable=True),
        sa.Column('status', sa.String),
        sa.Column('reason', sa.String, nullable=True),
        sa.Column('risk_note', sa.String, nullable=True),
        sa.Column('created_at', sa.DateTime, index=True),
        sa.Column('resolved_at', sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table('chat_action')
