from sqlalchemy.orm import Session
from app.models.models import InstitutionalPosition
import datetime

def ingest_13f_data(db: Session, data: list):
    """
    Data should be a list of dicts: 
    [{'fund_name': '...', 'ticker': '...', 'shares': ..., 'value': ..., 'quarter': '...'}]
    """
    for item in data:
        # Simplified: just add. In reality, check for duplicates or update.
        pos = InstitutionalPosition(
            fund_name=item['fund_name'],
            ticker=item['ticker'],
            shares=item['shares'],
            value=item['value'],
            quarter=item['quarter'],
            conviction_score=item.get('conviction_score', 0.0)
        )
        db.add(pos)
    db.commit()
