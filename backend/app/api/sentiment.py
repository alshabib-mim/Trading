"""News & sentiment read API — the latest stored sentiment per asset
(headlines Claude read + its rationale + normalized score).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.models import SentimentScore, User

router = APIRouter()


@router.get("/")
def get_sentiment(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.query(SentimentScore).order_by(SentimentScore.timestamp.desc()).all()
    latest = {}
    for r in rows:
        if r.asset in latest:
            continue
        latest[r.asset] = {
            "asset": r.asset,
            "score": r.score,
            "rationale": r.rationale,
            "headlines": r.headlines or [],
            "source": r.source,
            "timestamp": r.timestamp,
        }
    return list(latest.values())
