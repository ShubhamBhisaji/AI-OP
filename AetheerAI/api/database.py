"""
database.py — SQLAlchemy / SQLite persistence layer.

Tables
------
users           login accounts (hashed passwords)
predictions     AI prediction records with confidence scores
uploaded_files  metadata for user-uploaded files
activity_logs   immutable audit trail of every API action
goal_runs       persisted goal/project execution records (survives restart)
tasks           individual agent tasks belonging to a goal run
system_logs     structured server-side log entries (INFO / WARNING / ERROR)
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


# ── GoalRun ────────────────────────────────────────────────────────────────

class GoalRun(Base):
    """Persisted record of a complete goal/project execution."""

    __tablename__ = "goal_runs"

    id               = Column(String(64),  primary_key=True, index=True)   # UUID from server
    name             = Column(String(256), nullable=False, index=True)
    goal             = Column(Text,        nullable=False)
    status           = Column(String(32),  nullable=False, default="pending", index=True)
    plan_summary     = Column(Text,        nullable=True)
    total_tasks      = Column(Integer,     nullable=False, default=0)
    completed_tasks  = Column(Integer,     nullable=False, default=0)
    failed_tasks     = Column(Integer,     nullable=False, default=0)
    spent_usd        = Column(Float,       nullable=True)
    elapsed_seconds  = Column(Float,       nullable=True)
    error            = Column(Text,        nullable=True)
    replanned        = Column(Boolean,     default=False, nullable=False)
    started_at       = Column(DateTime,    nullable=True,  index=True)
    completed_at     = Column(DateTime,    nullable=True)
    created_at       = Column(DateTime,    default=datetime.datetime.utcnow, nullable=False)

    tasks = relationship("Task", back_populates="goal_run", cascade="all, delete-orphan",
                         order_by="Task.task_index")

    def to_dict(self, *, include_tasks: bool = False) -> dict:
        d = {
            "id":              self.id,
            "name":            self.name,
            "goal":            self.goal,
            "status":          self.status,
            "plan_summary":    self.plan_summary,
            "total_tasks":     self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks":    self.failed_tasks,
            "spent_usd":       self.spent_usd,
            "elapsed_seconds": self.elapsed_seconds,
            "error":           self.error,
            "replanned":       self.replanned,
            "started_at":      self.started_at.isoformat()   if self.started_at   else None,
            "completed_at":    self.completed_at.isoformat() if self.completed_at else None,
            "created_at":      self.created_at.isoformat()   if self.created_at   else None,
            "progress": {
                "completed": self.completed_tasks,
                "failed":    self.failed_tasks,
                "total":     self.total_tasks,
                "percent":   round(
                    (self.completed_tasks / max(1, self.total_tasks)) * 100, 2
                ),
            },
        }
        if include_tasks:
            d["tasks"] = [t.to_dict() for t in (self.tasks or [])]
        return d


# ── Task ───────────────────────────────────────────────────────────────────

class Task(Base):
    """An individual agent task that belongs to a GoalRun."""

    __tablename__ = "tasks"

    id          = Column(Integer,     primary_key=True, index=True)
    task_uuid   = Column(String(64),  nullable=True,  index=True)   # task_id from CEOAgent
    goal_id     = Column(String(64),  ForeignKey("goal_runs.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    task_index  = Column(Integer,     nullable=False, default=0)
    title       = Column(String(512), nullable=False, default="")
    description = Column(Text,        nullable=True)
    agent_type  = Column(String(128), nullable=True,  index=True)
    role_description = Column(Text,   nullable=True)
    priority    = Column(Integer,     nullable=False, default=1)
    depends_on  = Column(JSON,        nullable=True)
    require_approval = Column(Boolean, default=False, nullable=False)
    status      = Column(String(32),  nullable=False, default="pending", index=True)
    result      = Column(Text,        nullable=True)
    error       = Column(Text,        nullable=True)
    attempts    = Column(Integer,     nullable=False, default=0)
    created_at  = Column(DateTime,    default=datetime.datetime.utcnow, nullable=False, index=True)

    goal_run = relationship("GoalRun", back_populates="tasks")

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "task_uuid":        self.task_uuid,
            "goal_id":          self.goal_id,
            "task_index":       self.task_index,
            "title":            self.title,
            "description":      self.description,
            "agent_type":       self.agent_type,
            "role_description": self.role_description,
            "priority":         self.priority,
            "depends_on":       self.depends_on or [],
            "require_approval": self.require_approval,
            "status":           self.status,
            "result":           self.result,
            "error":            self.error,
            "attempts":         self.attempts,
            "created_at":       self.created_at.isoformat() if self.created_at else None,
        }


# ── SystemLog ──────────────────────────────────────────────────────────────

class SystemLog(Base):
    """Structured server-side log entries written by the SQLite log handler."""

    __tablename__ = "system_logs"

    id          = Column(Integer,     primary_key=True, index=True)
    level       = Column(String(16),  nullable=False, default="INFO", index=True)
    logger_name = Column(String(128), nullable=True,  index=True)
    message     = Column(Text,        nullable=False)
    context     = Column(JSON,        nullable=True)   # extra kwargs / exc_info
    created_at  = Column(DateTime,    default=datetime.datetime.utcnow, nullable=False, index=True)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "level":       self.level,
            "logger_name": self.logger_name,
            "message":     self.message,
            "context":     self.context,
            "created_at":  self.created_at.isoformat() if self.created_at else None,
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
