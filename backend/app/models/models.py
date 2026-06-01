from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, Float, Boolean, ForeignKey, JSON, Enum
from sqlalchemy.orm import relationship
import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    role = Column(String, default="owner") # owner, viewer

class SourceConfig(Base):
    __tablename__ = "source_config"
    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, unique=True, index=True, nullable=False) # technical, whale, institutional, sentiment
    provider = Column(String, nullable=False)
    credentials_encrypted = Column(String, nullable=True) # AES-256-GCM token; null = no key needed
    enabled = Column(Boolean, default=False)
    weight = Column(Float, default=1.0)
    freshness_seconds = Column(Integer)
    interval_seconds = Column(Integer)
    options = Column(JSON, nullable=True) # provider-specific params
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class AssetConfig(Base):
    __tablename__ = "asset_config"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, unique=True, index=True, nullable=False)  # AAPL, BTC-USD
    asset_type = Column(String, nullable=False)                       # stock | crypto
    enabled = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class InstitutionalPosition(Base):
    __tablename__ = "institutional_positions"
    id = Column(Integer, primary_key=True, index=True)
    fund_name = Column(String, index=True)
    ticker = Column(String, index=True)
    shares = Column(Float)
    value = Column(Float)
    conviction_score = Column(Float)
    quarter = Column(String)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

class WhaleMovement(Base):
    __tablename__ = "whale_movements"
    id = Column(Integer, primary_key=True, index=True)
    asset = Column(String, index=True) # BTC, ETH
    amount = Column(Float)
    transaction_type = Column(String) # inflow, outflow
    source = Column(String)
    timestamp = Column(DateTime, index=True)

class InsiderTransaction(Base):
    __tablename__ = "insider_transactions"
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, index=True)
    cik = Column(String)
    insider_name = Column(String)
    transaction_code = Column(String)  # P = open-market buy (the bullish signal)
    shares = Column(Float)
    price = Column(Float)
    value = Column(Float)              # shares * price
    transaction_date = Column(String)  # as-reported YYYY-MM-DD
    accession = Column(String, index=True)  # EDGAR filing id; used to dedupe re-runs
    filed_date = Column(DateTime)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class TechnicalSignal(Base):
    __tablename__ = "technical_signals"
    id = Column(Integer, primary_key=True, index=True)
    asset = Column(String, index=True)
    indicator_name = Column(String)
    value = Column(Float)
    signal_type = Column(String) # buy, sell, neutral
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

class SentimentScore(Base):
    __tablename__ = "sentiment_scores"
    id = Column(Integer, primary_key=True, index=True)
    asset = Column(String, index=True)
    score = Column(Float) # normalized 0..1 (0=bearish, 0.5=neutral, 1=bullish)
    rationale = Column(String)
    headlines = Column(JSON, nullable=True)  # the exact headlines Claude scored
    source = Column(String)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

class MacroBias(Base):
    """Per-currency macro bias snapshot for forex news (4th signal source).
    Claude scores each currency's bias (bullish/bearish/neutral/insufficient) from
    high-impact macro releases; gold gets a DIRECT per-pair read (not decomposed).
    Pair direction is derived deterministically in code (base − quote arithmetic).
    """
    __tablename__ = "macro_bias"
    id = Column(Integer, primary_key=True, index=True)
    currencies = Column(JSON)  # {"USD": {"bias": "bullish", "strength": 0.6, "why": "..."}, ...}
    gold = Column(JSON, nullable=True)  # {"direction": "bearish", "strength": 0.5, "why": "..."} — direct XAU-USD read
    model = Column(String, nullable=True)   # which Claude model produced it
    raw = Column(String, nullable=True)     # full model text, for audit
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)


class TradingSignal(Base):
    __tablename__ = "trading_signals"
    id = Column(Integer, primary_key=True, index=True)
    asset = Column(String, index=True)
    direction = Column(String) # bullish, bearish, none
    signal_type = Column(String) # buy, sell
    confidence_score = Column(Float)  # armed-confidence (gated by timing)
    direction_conviction = Column(Float, nullable=True)  # raw 0-1 strength of the direction source
    status = Column(String) # watch, pending, approved, rejected, executed
    institutional_conf = Column(Boolean)
    whale_conf = Column(Boolean)
    technical_conf = Column(Boolean)
    sentiment_conf = Column(Boolean)
    news_conf = Column(Boolean, nullable=True)  # forex macro news confirms direction (forex only)
    reasoning = Column(String, nullable=True) # Claude reasoning layer, only on armed signals
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

class ExecutedTrade(Base):
    __tablename__ = "executed_trades"
    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(Integer, ForeignKey("trading_signals.id"))
    asset = Column(String, index=True)
    entry_price = Column(Float)
    exit_price = Column(Float, nullable=True)
    size = Column(Float)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)
    status = Column(String) # open, closed
    side = Column(String, nullable=True)  # long, short
    close_reason = Column(String, nullable=True)  # stop, target, manual
    overrides = Column(JSON, nullable=True)  # per-trade guardrail overrides (stop_loss/take_profit only)
    entry_time = Column(DateTime, default=datetime.datetime.utcnow)
    exit_time = Column(DateTime, nullable=True)
    explanation = Column(String, nullable=True) # Claude's explanation

class RiskConfig(Base):
    __tablename__ = "risk_config"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True, nullable=False)  # account, daily_loss, drawdown, max_concurrent, stop_loss, take_profit
    enabled = Column(Boolean, default=True)
    params = Column(JSON, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class RiskState(Base):
    __tablename__ = "risk_state"
    id = Column(Integer, primary_key=True, index=True)
    peak_equity = Column(Float)
    day_date = Column(String, nullable=True)        # YYYY-MM-DD of the current day baseline
    day_start_equity = Column(Float, nullable=True)
    manual_halt = Column(Boolean, default=False)    # owner-settable kill switch
    halt_alerted = Column(String, nullable=True)    # signature of the last halt alerted (edge-trigger; alert once per episode)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class AlertConfig(Base):
    """Single-row config for the outbound alerts channel (Telegram). Bot token and
    chat id are AES-256-GCM encrypted at rest (same as source credentials); events
    is a per-event-type enable map. Master `enabled` gates everything."""
    __tablename__ = "alert_config"
    id = Column(Integer, primary_key=True, index=True)
    channel = Column(String, default="telegram")
    enabled = Column(Boolean, default=False)              # master switch (ships off)
    bot_token_encrypted = Column(String, nullable=True)
    chat_id_encrypted = Column(String, nullable=True)
    events = Column(JSON)  # {"signal_armed": true, "position_opened": true, "exit_hit": true, "breaker": true}
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class BrokerAccount(Base):
    __tablename__ = "broker_accounts"
    id = Column(Integer, primary_key=True, index=True)
    broker_name = Column(String) # Interactive Brokers, Alpaca, etc.
    account_id = Column(String)
    api_key = Column(String)
    api_secret = Column(String)
    balance = Column(Float)
    is_active = Column(Boolean, default=True)

class PerformanceMetric(Base):
    __tablename__ = "performance_metrics"
    id = Column(Integer, primary_key=True, index=True)
    period = Column(String) # daily, weekly, monthly
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    win_rate = Column(Float)
    profit_factor = Column(Float)
    sharpe_ratio = Column(Float)
    total_pnl = Column(Float)
