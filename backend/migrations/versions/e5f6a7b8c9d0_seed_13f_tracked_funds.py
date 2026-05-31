"""Seed the institutional (13F) source with tracked-fund CIKs

Funds (looked up on EDGAR): Berkshire Hathaway, Scion Asset Management,
Pershing Square, Appaloosa, Greenlight Capital, Third Point. 13F stays
support-only.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-31

"""
import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


source_config = sa.table(
    'source_config',
    sa.column('source', sa.String),
    sa.column('options', sa.JSON),
    sa.column('updated_at', sa.DateTime),
)

_FUNDS = [
    {"cik": "1067983", "name": "Berkshire Hathaway"},
    {"cik": "1649339", "name": "Scion Asset Management"},
    {"cik": "1336528", "name": "Pershing Square"},
    {"cik": "1656456", "name": "Appaloosa"},
    {"cik": "1079114", "name": "Greenlight Capital"},
    {"cik": "1040273", "name": "Third Point"},
]


def upgrade() -> None:
    op.execute(
        source_config.update()
        .where(source_config.c.source == 'institutional')
        .values(
            options={"form_type": "13F-HR", "funds": _FUNDS},
            updated_at=datetime.datetime.utcnow(),
        )
    )


def downgrade() -> None:
    op.execute(
        source_config.update()
        .where(source_config.c.source == 'institutional')
        .values(
            options={"form_type": "13F-HR", "funds": []},
            updated_at=datetime.datetime.utcnow(),
        )
    )
