import os
from pathlib import Path
from dotenv import load_dotenv

# Load backend/.env before any module reads os.getenv at import time.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth, signals, trades, config, charts, risk, sentiment
from app.core.crypto import validate_encryption_key
from app.tasks.scheduler import start_scheduler

app = FastAPI(title="AI Trading System API")

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://209.97.174.40").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(signals.router, prefix="/api/signals", tags=["signals"])
app.include_router(trades.router, prefix="/api/trades", tags=["trades"])
app.include_router(config.router, prefix="/api/config", tags=["config"])
app.include_router(charts.router, prefix="/api/charts", tags=["charts"])
app.include_router(risk.router, prefix="/api/risk", tags=["risk"])
app.include_router(sentiment.router, prefix="/api/news", tags=["news"])

@app.on_event("startup")
def startup_event():
    validate_encryption_key()
    start_scheduler()

@app.get("/")
def read_root():
    return {"message": "Welcome to AI-Powered Multi-Market Trading System API"}
