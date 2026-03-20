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
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

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
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

from api.request_context import get_request_user_id


logger = logging.getLogger("aetheer.api.database")

# ── Database location ──────────────────────────────────────────────────────
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_bool(name: str) -> bool:
    raw = (os.getenv(name) or "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
        raw = raw[1:-1].strip()
    return raw.lower() in _TRUE_VALUES


def _is_serverless_runtime() -> bool:
    if _env_bool("VERCEL") or _env_bool("AETHEER_SERVERLESS_MODE"):
        return True

    for marker in ("VERCEL_URL", "AWS_LAMBDA_FUNCTION_NAME", "AWS_EXECUTION_ENV", "NOW_REGION"):
        if (os.getenv(marker) or "").strip():
            return True
    return False


def _default_sqlite_url() -> str:
    if _is_serverless_runtime():
        db_dir = Path(tempfile.gettempdir()) / "aetheer_memory"
    else:
        db_dir = Path(__file__).resolve().parents[1] / "memory"
    return f"sqlite:///{db_dir / 'aetheer.db'}"


def _sanitize_db_url(raw_url: str) -> str:
    value = str(raw_url or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()

    # Guard against accidental escaped newlines appended via shell piping.
    while value.endswith("\\r\\n"):
        value = value[:-4].rstrip()
    while value.endswith("\\n") or value.endswith("\\r"):
        value = value[:-2].rstrip()

    return value.rstrip("\r\n").strip()


def _prepare_sqlite_directory(db_url: str) -> None:
    if not db_url.startswith("sqlite:///"):
        return

    path_part = db_url[len("sqlite:///"):].strip()
    if not path_part or path_part == ":memory:":
        return

    db_path = Path(path_part)
    if not db_path.is_absolute():
        db_path = (Path.cwd() / db_path).resolve()

    db_path.parent.mkdir(parents=True, exist_ok=True)


_DB_URL = _sanitize_db_url(os.getenv("DATABASE_URL") or _default_sqlite_url())
if not _DB_URL:
    _DB_URL = _default_sqlite_url()
_prepare_sqlite_directory(_DB_URL)

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


_MIRROR_HOOKS_ATTACHED = False


# ── Models ─────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id         = Column(Integer, primary_key=True, index=True)
    supabase_user_id = Column(String(36), unique=True, nullable=True, index=True)  # UUID from Supabase
    username   = Column(String(64), unique=True, nullable=False, index=True)
    email      = Column(String(200), unique=True, nullable=False, index=True)
    hashed_pw  = Column(String(256), nullable=False)
    is_admin   = Column(Boolean, default=False, nullable=False)
    is_active  = Column(Boolean, default=True,  nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    predictions = relationship("Prediction",   back_populates="user", cascade="all, delete-orphan")
    uploads     = relationship("UploadedFile", back_populates="user", cascade="all, delete-orphan")
    logs        = relationship("ActivityLog",  back_populates="user", cascade="all, delete-orphan")
    subscriptions = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")
    invoices      = relationship("BillingInvoice", back_populates="user", cascade="all, delete-orphan")
    usage_events  = relationship("UsageEvent", back_populates="user", cascade="all, delete-orphan")

    def to_dict(self, *, include_private: bool = False) -> dict:
        d = {
            "id":         self.id,
            "username":   self.username,
            "email":      self.email,
            "role":       "admin" if self.is_admin else "user",
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


class RevokedAuthToken(Base):
    """Persisted blacklist entry for JWTs that have been logged out."""

    __tablename__ = "revoked_auth_tokens"

    token_hash = Column(String(64), primary_key=True, index=True)
    user_id    = Column(Integer, nullable=True, index=True)
    revoked_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    reason     = Column(String(128), nullable=True)

    def to_dict(self) -> dict:
        return {
            "token_hash": self.token_hash,
            "user_id": self.user_id,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "reason": self.reason,
        }


class BillingPlan(Base):
    __tablename__ = "billing_plans"

    id          = Column(Integer, primary_key=True, index=True)
    code        = Column(String(64), unique=True, nullable=False, index=True)
    name        = Column(String(128), nullable=False)
    interval    = Column(String(16), nullable=False, default="monthly")  # monthly | yearly
    price_usd   = Column(Float, nullable=False, default=0.0)
    token_quota = Column(Integer, nullable=True)
    features    = Column(JSON, nullable=True)
    is_active   = Column(Boolean, default=True, nullable=False, index=True)
    created_at  = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at  = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )

    subscriptions = relationship("Subscription", back_populates="plan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "interval": self.interval,
            "price_usd": self.price_usd,
            "token_quota": self.token_quota,
            "features": self.features or {},
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Subscription(Base):
    __tablename__ = "subscriptions"

    id                    = Column(Integer, primary_key=True, index=True)
    user_id               = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id               = Column(Integer, ForeignKey("billing_plans.id", ondelete="SET NULL"), nullable=True, index=True)
    status                = Column(String(24), nullable=False, default="active", index=True)  # active | cancelled | past_due
    current_period_start  = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    current_period_end    = Column(DateTime, nullable=False)
    cancel_at_period_end  = Column(Boolean, default=False, nullable=False)
    created_at            = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at            = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )

    user   = relationship("User", back_populates="subscriptions")
    plan   = relationship("BillingPlan", back_populates="subscriptions")
    invoices = relationship("BillingInvoice", back_populates="subscription")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "plan_id": self.plan_id,
            "status": self.status,
            "current_period_start": self.current_period_start.isoformat() if self.current_period_start else None,
            "current_period_end": self.current_period_end.isoformat() if self.current_period_end else None,
            "cancel_at_period_end": self.cancel_at_period_end,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class BillingInvoice(Base):
    __tablename__ = "billing_invoices"

    id               = Column(Integer, primary_key=True, index=True)
    subscription_id  = Column(Integer, ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id          = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    amount_usd       = Column(Float, nullable=False, default=0.0)
    currency         = Column(String(8), nullable=False, default="USD")
    status           = Column(String(24), nullable=False, default="open", index=True)  # open | paid | void
    period_start     = Column(DateTime, nullable=False)
    period_end       = Column(DateTime, nullable=False)
    due_at           = Column(DateTime, nullable=True)
    paid_at          = Column(DateTime, nullable=True)
    meta             = Column(JSON, nullable=True)
    created_at       = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    subscription = relationship("Subscription", back_populates="invoices")
    user         = relationship("User", back_populates="invoices")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "subscription_id": self.subscription_id,
            "user_id": self.user_id,
            "amount_usd": self.amount_usd,
            "currency": self.currency,
            "status": self.status,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "meta": self.meta or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type  = Column(String(64), nullable=False, index=True)
    metric_name = Column(String(64), nullable=False, index=True)
    quantity    = Column(Float, nullable=False, default=1.0)
    unit        = Column(String(32), nullable=False, default="count")
    meta        = Column(JSON, nullable=True)
    created_at  = Column(DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)

    user = relationship("User", back_populates="usage_events")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "event_type": self.event_type,
            "metric_name": self.metric_name,
            "quantity": self.quantity,
            "unit": self.unit,
            "meta": self.meta or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ── GoalRun ────────────────────────────────────────────────────────────────

class GoalRun(Base):
    """Persisted record of a complete goal/project execution."""

    __tablename__ = "goal_runs"

    id               = Column(String(64),  primary_key=True, index=True)   # UUID from server
    owner_user_id    = Column(Integer,     nullable=True, index=True)
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
    owner_user_id = Column(Integer,   nullable=True, index=True)
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
    _apply_runtime_schema_migrations()
    _install_customer_mirror_hooks()


def _quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _ensure_optional_column(
    table_name: str,
    column_name: str,
    ddl: str,
    *,
    index_name: str | None = None,
) -> None:
    inspector = inspect(engine)
    existing = {str(col.get("name") or "").strip() for col in inspector.get_columns(table_name)}
    if column_name in existing:
        return

    table_sql = _quote_identifier(table_name)
    column_sql = _quote_identifier(column_name)

    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table_sql} ADD COLUMN {column_sql} {ddl}"))
        if index_name:
            index_sql = _quote_identifier(index_name)
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_sql} ON {table_sql} ({column_sql})"))


def _apply_runtime_schema_migrations() -> None:
    try:
        _ensure_optional_column(
            "users",
            "supabase_user_id",
            "VARCHAR(36)",
            index_name="idx_users_supabase_user_id",
        )
        _ensure_optional_column(
            "goal_runs",
            "owner_user_id",
            "INTEGER",
            index_name="idx_goal_runs_owner_user_id",
        )
        _ensure_optional_column(
            "tasks",
            "owner_user_id",
            "INTEGER",
            index_name="idx_tasks_owner_user_id",
        )
    except Exception as exc:
        logger.warning("Runtime schema migration skipped: %s", exc)


def _normalize_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return [_normalize_json_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _normalize_json_value(v) for k, v in value.items()}
    return str(value)


def _row_payload(target: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    table = getattr(target, "__table__", None)
    columns = getattr(table, "columns", [])
    for col in columns:
        name = str(getattr(col, "name", "")).strip()
        if not name:
            continue
        try:
            payload[name] = _normalize_json_value(getattr(target, name))
        except Exception:
            payload[name] = None
    return payload


def _owner_user_id_for_row(target: Any) -> int | None:
    for attr in ("user_id", "owner_user_id"):
        raw = getattr(target, attr, None)
        if raw is None:
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue

    if isinstance(target, User):
        try:
            return int(target.id)
        except (TypeError, ValueError):
            return None

    try:
        context_user_id = get_request_user_id()
        if context_user_id is not None:
            return int(context_user_id)
    except Exception:
        return None
    return None


def _source_row_id_for(target: Any) -> str:
    for attr in ("id", "task_uuid", "code"):
        raw = getattr(target, attr, None)
        if raw not in (None, ""):
            return str(raw)
    return ""


def _mirror_row_change(operation: str, target: Any) -> None:
    owner_user_id = _owner_user_id_for_row(target)
    if owner_user_id is None:
        return

    table_name = str(getattr(target, "__tablename__", "")).strip() or target.__class__.__name__.lower()
    source_row_id = _source_row_id_for(target)
    payload = _row_payload(target)

    try:
        from api.customer_supabase import mirror_db_entry_best_effort

        mirror_db_entry_best_effort(
            user_id=owner_user_id,
            source_table=table_name,
            operation=operation,
            source_row_id=source_row_id,
            payload=payload,
        )
    except Exception as exc:
        logger.warning(
            "Local->customer Supabase mirror failed (table=%s op=%s user=%s): %s",
            table_name,
            operation,
            owner_user_id,
            exc,
        )


def _after_insert(_mapper, _connection, target) -> None:
    _mirror_row_change("insert", target)


def _after_update(_mapper, _connection, target) -> None:
    _mirror_row_change("update", target)


def _after_delete(_mapper, _connection, target) -> None:
    _mirror_row_change("delete", target)


def _install_customer_mirror_hooks() -> None:
    global _MIRROR_HOOKS_ATTACHED
    if _MIRROR_HOOKS_ATTACHED:
        return

    tracked_models = (
        User,
        Prediction,
        UploadedFile,
        ActivityLog,
        BillingPlan,
        Subscription,
        BillingInvoice,
        UsageEvent,
        GoalRun,
        Task,
        SystemLog,
    )

    for model in tracked_models:
        event.listen(model, "after_insert", _after_insert)
        event.listen(model, "after_update", _after_update)
        event.listen(model, "after_delete", _after_delete)

    _MIRROR_HOOKS_ATTACHED = True
