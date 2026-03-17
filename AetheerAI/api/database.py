"""
database.py — SQLAlchemy / SQLite persistence layer.

Tables
------
users           login accounts (hashed passwords)
predictions     AI prediction records with confidence scores
uploaded_files  metadata for user-uploaded files
activity_logs   immutable audit trail of every API action
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

# ── Database location ──────────────────────────────────────────────────────
_DB_DIR = Path(__file__).resolve().parents[1] / "memory"
_DB_DIR.mkdir(parents=True, exist_ok=True)
_DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{_DB_DIR / 'aetheer.db'}")

engine = create_engine(
    _DB_URL,
    connect_args={"check_same_thread": False} if _DB_URL.startswith("sqlite") else {},
    echo=False,
)

# Enable WAL mode on SQLite for concurrent reads
if _DB_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_wal(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


# ── Models ─────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id         = Column(Integer, primary_key=True, index=True)
    username   = Column(String(64), unique=True, nullable=False, index=True)
    email      = Column(String(200), unique=True, nullable=False, index=True)
    hashed_pw  = Column(String(256), nullable=False)
    is_admin   = Column(Boolean, default=False, nullable=False)
    is_active  = Column(Boolean, default=True,  nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    predictions = relationship("Prediction",   back_populates="user", cascade="all, delete-orphan")
    uploads     = relationship("UploadedFile", back_populates="user", cascade="all, delete-orphan")
    logs        = relationship("ActivityLog",  back_populates="user", cascade="all, delete-orphan")

    def to_dict(self, *, include_private: bool = False) -> dict:
        d = {
            "id":         self.id,
            "username":   self.username,
            "email":      self.email,
            "is_admin":   self.is_admin,
            "is_active":  self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        return d


class Prediction(Base):
    __tablename__ = "predictions"

    id            = Column(Integer, primary_key=True, index=True)
    user_id       = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    input_text    = Column(Text,    nullable=True)
    input_file_id = Column(Integer, ForeignKey("uploaded_files.id", ondelete="SET NULL"), nullable=True)
    model_used    = Column(String(128), nullable=False, default="")
    provider      = Column(String(64),  nullable=False, default="")
    result        = Column(Text,    nullable=True)
    confidence    = Column(Float,   nullable=True)      # 0.0 – 1.0
    alternatives  = Column(JSON,    nullable=True)      # list[{model, provider, result, confidence}]
    tokens_used   = Column(Integer, nullable=True)
    cost_usd      = Column(Float,   nullable=True)
    latency_ms    = Column(Integer, nullable=True)
    status        = Column(String(32), default="completed", nullable=False)
    error         = Column(Text,    nullable=True)
    created_at    = Column(DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)

    user        = relationship("User",         back_populates="predictions")
    input_file  = relationship("UploadedFile", back_populates="predictions")

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "user_id":       self.user_id,
            "input_text":    self.input_text,
            "input_file_id": self.input_file_id,
            "model_used":    self.model_used,
            "provider":      self.provider,
            "result":        self.result,
            "confidence":    self.confidence,
            "alternatives":  self.alternatives or [],
            "tokens_used":   self.tokens_used,
            "cost_usd":      self.cost_usd,
            "latency_ms":    self.latency_ms,
            "status":        self.status,
            "error":         self.error,
            "created_at":    self.created_at.isoformat() if self.created_at else None,
        }


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    filename     = Column(String(256), nullable=False)
    content_type = Column(String(128), nullable=True)
    size_bytes   = Column(Integer,     nullable=True)
    storage_path = Column(String(512), nullable=False)
    created_at   = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    user        = relationship("User",       back_populates="uploads")
    predictions = relationship("Prediction", back_populates="input_file")

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "user_id":      self.user_id,
            "filename":     self.filename,
            "content_type": self.content_type,
            "size_bytes":   self.size_bytes,
            "created_at":   self.created_at.isoformat() if self.created_at else None,
        }


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action     = Column(String(128), nullable=False, index=True)
    detail     = Column(JSON,  nullable=True)
    ip_address = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)

    user = relationship("User", back_populates="logs")

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "user_id":    self.user_id,
            "action":     self.action,
            "detail":     self.detail,
            "ip_address": self.ip_address,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ── Helpers ────────────────────────────────────────────────────────────────

def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (idempotent — safe to call on every startup)."""
    Base.metadata.create_all(bind=engine)
