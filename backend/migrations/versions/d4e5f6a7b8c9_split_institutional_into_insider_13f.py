"""Split the institutional source into insider (Form 4) + institutional (13F)

Both move to the EDGAR provider. `insider` is the fast stock-DIRECTION feed
(Form 4 open-market buys). `institutional` is demoted to slow SUPPORT-only 13F
(its adapter feed is wired in a later pass; row seeded disabled).

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-31

"""
import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
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
    now = datetime.datetime.utcnow()

    # Demote the existing institutional row to EDGAR 13F support-only.
    op.execute(
        source_config.update()
        .where(source_config.c.source == 'institutional')
        .values(
            provider='edgar',
            weight=0.3,
            freshness_seconds=7776000,   # ~90 days (quarterly)
            interval_seconds=86400,      # daily poll, cheap
            options={"form_type": "13F-HR", "funds": []},
            updated_at=now,
        )
    )

    # Add the fast Form 4 insider direction feed (seeded disabled until verified).
    op.bulk_insert(source_config, [
        {
            'source': 'insider', 'provider': 'edgar', 'credentials_encrypted': None,
            'enabled': False, 'weight': 1.0,
            'freshness_seconds': 1209600,   # 14 days
            'interval_seconds': 21600,      # 6 hours
            'options': {
                "form_type": "4",
                "lookback_days": 30,
                "transaction_codes": ["P"],  # open-market buys only
                "buyer_scale": 3,
                "value_scale": 500000,
            },
            'updated_at': now,
        },
    ])


def downgrade() -> None:
    now = datetime.datetime.utcnow()
    op.execute(
        source_config.delete().where(source_config.c.source == 'insider')
    )
    op.execute(
        source_config.update()
        .where(source_config.c.source == 'institutional')
        .values(
            provider='sec_api',
            weight=1.0,
            freshness_seconds=7776000,
            interval_seconds=86400,
            options=None,
            updated_at=now,
        )
    )
