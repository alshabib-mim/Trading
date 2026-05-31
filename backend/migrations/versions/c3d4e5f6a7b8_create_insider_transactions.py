"""Create insider_transactions (Form 4 raw trail)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'insider_transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ticker', sa.String(), nullable=True),
        sa.Column('cik', sa.String(), nullable=True),
        sa.Column('insider_name', sa.String(), nullable=True),
        sa.Column('transaction_code', sa.String(), nullable=True),
        sa.Column('shares', sa.Float(), nullable=True),
        sa.Column('price', sa.Float(), nullable=True),
        sa.Column('value', sa.Float(), nullable=True),
        sa.Column('transaction_date', sa.String(), nullable=True),
        sa.Column('accession', sa.String(), nullable=True),
        sa.Column('filed_date', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_insider_transactions_id'), 'insider_transactions', ['id'], unique=False)
    op.create_index(op.f('ix_insider_transactions_ticker'), 'insider_transactions', ['ticker'], unique=False)
    op.create_index(op.f('ix_insider_transactions_accession'), 'insider_transactions', ['accession'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_insider_transactions_accession'), table_name='insider_transactions')
    op.drop_index(op.f('ix_insider_transactions_ticker'), table_name='insider_transactions')
    op.drop_index(op.f('ix_insider_transactions_id'), table_name='insider_transactions')
    op.drop_table('insider_transactions')
