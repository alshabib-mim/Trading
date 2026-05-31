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
    score = Column(Float) # 0-100
    rationale = Column(String)
    source = Column(String)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

class TradingSignal(Base):
    __tablename__ = "trading_signals"
    id = Column(Integer, primary_key=True, index=True)
    asset = Column(String, index=True)
    signal_type = Column(String) # buy, sell
    confidence_score = Column(Float)
    status = Column(String) # pending, approved, rejected, executed
    institutional_conf = Column(Boolean)
    whale_conf = Column(Boolean)
    technical_conf = Column(Boolean)
    sentiment_conf = Column(Boolean)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

class ExecutedTrade(Base):
    __tablename__ = "executed_trades"
    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(Integer, ForeignKey("trading_signals.id"))
    asset = Column(String, index=True)
    entry_price = Column(Float)
    exit_price = Column(Float, nullable=True)
    size = Column(Float)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    pnl = Column(Float, nullable=True)
    status = Column(String) # open, closed
    entry_time = Column(DateTime, default=datetime.datetime.utcnow)
    exit_time = Column(DateTime, nullable=True)
    explanation = Column(String, nullable=True) # Claude's explanation

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
