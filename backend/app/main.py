from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth, signals, trades
from app.tasks.scheduler import start_scheduler

app = FastAPI(title="AI Trading System API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(signals.router, prefix="/api/signals", tags=["signals"])
app.include_router(trades.router, prefix="/api/trades", tags=["trades"])

@app.on_event("startup")
def startup_event():
    start_scheduler()

@app.get("/")
def read_root():
    return {"message": "Welcome to AI-Powered Multi-Market Trading System API"}
