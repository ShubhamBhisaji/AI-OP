"""FastAPI backend for AetheerAI autonomous multi-agent operations."""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import hmac
import json
import logging
import os
import sys
import tempfile
import threading
import time
import uuid
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncGenerator

# Ensure local package imports work when running the module directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ai.ai_adapter import AIAdapter, SUPPORTED_PROVIDERS
from api.auth import (
    authenticate_bearer_token,
    resolve_bearer_user_from_request,
    router as auth_router,
)
from api.customer_supabase import (
    get_customer_ai_api_settings,
    is_customer_supabase_configured,
    record_user_agent_profile_best_effort,
    record_user_analytics_log_best_effort,
    record_user_token_usage_best_effort,
    save_customer_ai_api_settings,
)
from api.database import GoalRun, SessionLocal, SystemLog, Task, init_db
from api.db_router import router as db_router
from api.meta_webhook_router import router as meta_webhook_router
from api.payu_webhook_router import router as payu_webhook_router
from api.product_router import router as product_router
from api.queue_router import (
    collect_queue_metrics_snapshot,
    queue_metrics_prometheus_text,
    router as queue_router,
)
from api.reports import router as reports_router
from api.request_context import reset_request_user, set_request_user
from core.env_loader import load_env
from core.production_runtime import ProductionRuntime, RuntimeConfig, TTLResponseCache
from use_cases import registry as use_case_registry

try:
    from api.predict import router as predict_router
except Exception as predict_import_exc:  # pragma: no cover - startup guard
    logging.getLogger("aetheer.api").error(
        "Predict router disabled due import failure: %s",
        predict_import_exc,
    )
    predict_router = APIRouter(tags=["Inference"])

if TYPE_CHECKING:
    from agents.ceo_agent import CEOAgent, ProjectResult
    from core.aetheerai_kernel import AetheerAiKernel


logger = logging.getLogger("aetheer.api")
# Root logger is configured by setup_logging() in the process entry point.
# Do not call basicConfig here — it would conflict with the central setup.


_ENV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_env(_ENV)

_boot_time = time.time()
_projects: dict[str, dict[str, Any]] = {}
_projects_lock = threading.Lock()
_kernel: "AetheerAiKernel | None" = None
_ceo: "CEOAgent | None" = None
_ml_engine = None
_local_predictor = None
_sqlite_log_handler: logging.Handler | None = None
_ai_switch_lock = threading.RLock()
_user_ai_runtime_cache: dict[int, tuple[float, str, str | None, str | None, str | None]] = {}
_user_ai_runtime_cache_lock = threading.Lock()
_user_ai_runtime_overrides: dict[int, tuple[float, str, str | None, str | None, str | None]] = {}
_kill_switch_active = False
_kill_switch_lock = threading.Lock()

_TRUE_VALUES = {"1", "true", "yes", "on"}
_API_ROLE_ORDER = {"reader": 1, "user": 1, "writer": 2, "admin": 3}
_api_keys_cache_raw: str | None = None
_api_keys_cache: dict[str, str] = {}


def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    if minimum is not None:
        return max(minimum, value)
    return value


def _env_float(name: str, default: float, minimum: float | None = None) -> float:
    raw = os.getenv(name, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    if minimum is not None:
        return max(minimum, value)
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
        raw = raw[1:-1].strip()
    raw = raw.lower()
    if not raw:
        return default
    return raw in _TRUE_VALUES


def _deployment_environment() -> str:
    return (
        (os.getenv("AETHEER_ENV") or "").strip().lower()
        or (os.getenv("ENVIRONMENT") or "").strip().lower()
        or (os.getenv("PYTHON_ENV") or "").strip().lower()
        or "development"
    )


def _login_required() -> bool:
    if os.getenv("AETHEER_REQUIRE_LOGIN") is not None:
        return _env_bool("AETHEER_REQUIRE_LOGIN", default=True)
    return True


def _enforce_customer_supabase_setup() -> bool:
    if os.getenv("AETHEER_ENFORCE_CUSTOMER_SUPABASE_SETUP") is not None:
        return _env_bool("AETHEER_ENFORCE_CUSTOMER_SUPABASE_SETUP", default=True)
    return True


def _trust_proxy_headers() -> bool:
    return _env_bool("AETHEER_TRUST_PROXY_HEADERS", default=False)


def _strict_api_keys_required() -> bool:
    if os.getenv("AETHEER_REQUIRE_API_KEYS") is not None:
        return _env_bool("AETHEER_REQUIRE_API_KEYS", default=False)
    return _deployment_environment() in {"prod", "production"}


def _parse_api_keys(raw: str) -> dict[str, str]:
    """
    Parse API keys from env.

    Accepted formats:
      - key1,key2                            (defaults to admin role)
      - reader:key_r,writer:key_w,admin:key_a
    """
    out: dict[str, str] = {}
    for chunk in (raw or "").split(","):
        entry = chunk.strip()
        if not entry:
            continue

        role = "admin"
        key = entry
        if ":" in entry:
            left, right = entry.split(":", 1)
            maybe_role = left.strip().lower()
            if maybe_role in _API_ROLE_ORDER:
                role = maybe_role
                key = right.strip()

        if key:
            out[key] = role
    return out


def _configured_api_keys() -> dict[str, str]:
    global _api_keys_cache_raw, _api_keys_cache

    raw = (os.getenv("AETHER_API_KEYS") or "").strip()
    if raw == _api_keys_cache_raw:
        return _api_keys_cache

    _api_keys_cache_raw = raw
    _api_keys_cache = _parse_api_keys(raw)
    return _api_keys_cache


def _required_role_for(path: str, method: str) -> str:
    upper_method = (method or "").upper()

    if upper_method == "DELETE":
        return "admin"

    if path.startswith("/api/logs") or path.startswith("/api/db/logs"):
        return "admin"

    if upper_method in {"POST", "PUT", "PATCH"}:
        return "writer"

    return "reader"


def _resolve_api_role(presented_key: str | None, configured: dict[str, str]) -> str | None:
    key = (presented_key or "").strip()
    if not key:
        return None

    for expected, role in configured.items():
        if hmac.compare_digest(key, expected):
            return role
    return None


def _is_serverless_runtime() -> bool:
    if _env_bool("VERCEL", default=False) or _env_bool("AETHEER_SERVERLESS_MODE", default=False):
        return True

    for marker in ("VERCEL_URL", "AWS_LAMBDA_FUNCTION_NAME", "AWS_EXECUTION_ENV", "NOW_REGION"):
        if (os.getenv(marker) or "").strip():
            return True
    return False


def _extract_bearer_token(raw_value: str | None) -> str | None:
    text = str(raw_value or "").strip()
    if not text:
        return None
    if text.lower().startswith("bearer "):
        token = text[7:].strip()
        return token or None
    return None


def _eager_kernel_boot_enabled() -> bool:
    if os.getenv("AETHEER_EAGER_KERNEL_BOOT") is not None:
        return _env_bool("AETHEER_EAGER_KERNEL_BOOT", default=True)
    return not _is_serverless_runtime()


def _readiness_requires_kernel_boot() -> bool:
    if os.getenv("AETHEER_READY_CHECK_KERNEL") is not None:
        return _env_bool("AETHEER_READY_CHECK_KERNEL", default=True)
    return not _is_serverless_runtime()


_runtime = ProductionRuntime(RuntimeConfig.from_env())
_request_slots = asyncio.Semaphore(_runtime.config.max_concurrent_requests)
_response_cache = TTLResponseCache(max_entries=64)
_instance_id = (
    os.getenv("AETHEER_INSTANCE_ID", "").strip()
    or f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
)
_health_cache_ttl = _env_float("AETHEER_HEALTH_CACHE_TTL_SECONDS", 2.0, minimum=0.05)
_status_cache_ttl = _env_float("AETHEER_STATUS_CACHE_TTL_SECONDS", 1.0, minimum=0.05)
_alert_hook_timeout_seconds = _env_float("AETHEER_ALERT_WEBHOOK_TIMEOUT_SECONDS", 4.0, minimum=0.5)
_alert_webhook_url = (_runtime.config.alert_webhook_url or "").strip()
_non_throttled_paths = {
    "/api/health",
    "/api/ready",
    "/api/metrics",
    "/status",
}


class _SQLiteLogHandler(logging.Handler):
    """Persist warning/error server logs into the system_logs SQLite table."""

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("sqlalchemy"):
            return

        db: Session | None = None
        try:
            context: dict[str, Any] | None = None
            event = getattr(record, "event", None)
            if event is not None:
                context = {"event": event}
            if record.exc_info:
                formatter = logging.Formatter()
                if context is None:
                    context = {}
                context["traceback"] = formatter.formatException(record.exc_info)

            db = SessionLocal()
            db.add(
                SystemLog(
                    level=record.levelname,
                    logger_name=record.name,
                    message=record.getMessage(),
                    context=context,
                )
            )
            db.commit()
        except Exception:
            self.handleError(record)
        finally:
            if db is not None:
                db.close()


def _resolve_ai_runtime() -> tuple[str, str]:
    provider = (
        (os.getenv("AETHEERAI_DEFAULT_PROVIDER") or "").strip().lower()
        or (os.getenv("AI_PROVIDER") or "").strip().lower()
        or "openai"
    )
    model = (
        (os.getenv("AETHEERAI_DEFAULT_MODEL") or "").strip()
        or (os.getenv("AI_MODEL") or "").strip()
        or "gpt-4o"
    )
    return provider, model


def _get_kernel() -> "AetheerAiKernel":
    global _kernel
    if _kernel is None:
        from core.aetheerai_kernel import AetheerAiKernel

        provider, model = _resolve_ai_runtime()
        _kernel = AetheerAiKernel(ai_provider=provider, model=model)
        logger.info("Kernel booted (provider=%s model=%s)", provider, model)
        # Attach governance to app state on lazy boot
        if hasattr(_kernel, "governance_runtime") and hasattr(app, "state"):
            app.state.governance = _kernel.governance_runtime
    return _kernel


def _get_ceo() -> "CEOAgent":
    global _ceo
    if _ceo is None:
        from agents.ceo_agent import CEOAgent

        kernel = _get_kernel()
        limits = _goal_runtime_limits()
        _ceo = CEOAgent(
            kernel,
            max_tasks=limits["max_tasks"],
            max_cost_usd=limits["max_cost_usd"],
            max_runtime_seconds=limits["max_runtime_seconds"],
            max_retries=limits["max_retries"],
        )
    return _ceo


def _goal_runtime_limits() -> dict[str, Any]:
    return {
        "max_tasks": _env_int("MAX_TASKS_PER_PROJECT", 50, minimum=1),
        "max_cost_usd": _env_float("MAX_COST_USD", 10.0, minimum=0.0),
        "max_runtime_seconds": _env_int("MAX_RUNTIME_SECONDS", 600, minimum=1),
        "max_retries": _env_int("MAX_RETRIES", 3, minimum=0),
    }


def _build_goal_ceo(
    *,
    provider: str | None = None,
    model: str | None = None,
    max_cost_usd: float | None = None,
    max_runtime_seconds: int | None = None,
) -> "CEOAgent":
    limits = _goal_runtime_limits()
    from agents.ceo_agent import CEOAgent

    if provider is None and model is None:
        kernel = _get_kernel()
    else:
        from core.aetheerai_kernel import AetheerAiKernel

        resolved_provider, resolved_model = _resolve_ai_runtime()
        kernel = AetheerAiKernel(
            ai_provider=(provider or resolved_provider).strip().lower(),
            model=(model or resolved_model).strip(),
        )

    resolved_max_cost_usd = (
        limits["max_cost_usd"]
        if max_cost_usd is None
        else max(0.0, float(max_cost_usd))
    )
    resolved_max_runtime_seconds = (
        limits["max_runtime_seconds"]
        if max_runtime_seconds is None
        else max(1, int(max_runtime_seconds))
    )

    return CEOAgent(
        kernel,
        max_tasks=limits["max_tasks"],
        max_cost_usd=resolved_max_cost_usd,
        max_runtime_seconds=resolved_max_runtime_seconds,
        max_retries=limits["max_retries"],
    )


def _get_ml_engine():
    """Lazy-load the ML engine so API boot remains fast when ML is unused."""
    global _ml_engine
    if _ml_engine is None:
        from core.ml_engine import MLEngine
        _ml_engine = MLEngine.load_or_create()
    return _ml_engine


def _get_local_predictor():
    """Lazy-load a local fallback model that always supports predict()."""
    global _local_predictor
    if _local_predictor is None:
        from core.local_predictor import LocalPredictor
        _local_predictor = LocalPredictor()
    return _local_predictor


def _cached_payload(cache_key: str, ttl_seconds: float, builder) -> dict[str, Any]:
    cached = _response_cache.get(cache_key)
    if cached is not None:
        return cached
    payload = builder()
    _response_cache.set(cache_key, payload, ttl_seconds)
    return payload


def _runtime_active_provider_model() -> tuple[str, str]:
    if _kernel is not None:
        return _kernel.ai_adapter.provider, _kernel.ai_adapter.model
    return _resolve_ai_runtime()


def _load_user_ai_runtime_preference(
    user_id: int,
) -> tuple[str, str | None, str | None, str | None] | None:
    ttl_seconds = 15.0
    now = time.time()
    with _user_ai_runtime_cache_lock:
        override = _user_ai_runtime_overrides.get(int(user_id))
    if override is not None:
        _, provider, model, api_key, base_url = override
        return provider, model, api_key, base_url

    with _user_ai_runtime_cache_lock:
        cached = _user_ai_runtime_cache.get(int(user_id))
    if cached is not None:
        cached_at, provider, model, api_key, base_url = cached
        if now - cached_at <= ttl_seconds:
            return provider, model, api_key, base_url

    try:
        row = get_customer_ai_api_settings(user_id=int(user_id), include_secret=True)
    except Exception:
        return None
    if not isinstance(row, dict):
        return None

    provider = str(row.get("provider") or "").strip().lower()
    if provider not in set(SUPPORTED_PROVIDERS):
        return None
    model_raw = str(row.get("model") or "").strip()
    model = model_raw or None
    api_key_raw = str(row.get("api_key") or "").strip()
    api_key = api_key_raw or None
    base_url_raw = str(row.get("base_url") or "").strip()
    base_url = base_url_raw or None

    with _user_ai_runtime_cache_lock:
        _user_ai_runtime_cache[int(user_id)] = (now, provider, model, api_key, base_url)
    return provider, model, api_key, base_url


def _invalidate_user_ai_runtime_preference(user_id: int | None) -> None:
    if user_id is None:
        return
    with _user_ai_runtime_cache_lock:
        _user_ai_runtime_cache.pop(int(user_id), None)
        _user_ai_runtime_overrides.pop(int(user_id), None)


def _apply_user_ai_runtime_preference(request: Request) -> None:
    user_id = _connection_user_id(request)
    if user_id is None:
        return

    preferred = _load_user_ai_runtime_preference(user_id)
    if preferred is None:
        return

    preferred_provider, preferred_model, preferred_api_key, preferred_base_url = preferred
    kernel = _get_kernel()
    with _ai_switch_lock:
        kernel.ai_adapter.configure_provider(
            preferred_provider,
            api_key=preferred_api_key,
            base_url=preferred_base_url,
        )
        current_provider = str(kernel.ai_adapter.provider or "").strip().lower()
        current_model = str(kernel.ai_adapter.model or "").strip()
        target_model = preferred_model or AIAdapter._default_model(preferred_provider)

        if current_provider == preferred_provider and current_model == target_model:
            return

        kernel.ai_adapter.switch(preferred_provider, preferred_model)
        _response_cache.invalidate("health")
        _response_cache.invalidate("system_status")


def _attempt_runtime_failover(error: Exception | str) -> None:
    reason = str(error)
    should_activate = _runtime.record_ai_failure(reason)
    if not should_activate:
        return
    if not _runtime.failover_enabled:
        return

    kernel = _get_kernel()
    target_provider = _runtime.config.failover_provider
    with _ai_switch_lock:
        target_model = _runtime.config.failover_model or kernel.ai_adapter.model
        current = (kernel.ai_adapter.provider, kernel.ai_adapter.model)
        if current == (target_provider, target_model):
            _runtime.mark_failover_activated("failover target already active")
            return

        try:
            kernel.ai_adapter.switch(target_provider, target_model)
            _runtime.mark_failover_activated(reason)
            logger.warning(
                "Automatic failover activated: %s/%s (reason=%s)",
                target_provider,
                target_model,
                reason,
            )
        except Exception as exc:
            _runtime.mark_failover_activation_failed(str(exc))
            logger.error("Automatic failover activation failed: %s", exc)


def _record_runtime_ai_success() -> None:
    _runtime.record_ai_success()


def _request_log_level(status_code: int) -> int:
    if status_code >= 500:
        return logging.ERROR
    if status_code >= 400:
        return logging.WARNING
    return logging.INFO


def _observability_settings() -> dict[str, Any]:
    return {
        "webhook_configured": bool(_alert_webhook_url),
        "webhook_timeout_seconds": _alert_hook_timeout_seconds,
        "error_rate_threshold_pct": _runtime.config.alert_error_rate_threshold_pct,
        "p95_latency_ms_threshold": _runtime.config.alert_p95_latency_ms_threshold,
        "saturation_threshold": _runtime.config.alert_saturation_threshold,
        "min_requests": _runtime.config.alert_min_requests,
        "cooldown_seconds": _runtime.config.alert_cooldown_seconds,
        "queue_running_timeout_seconds": _env_int("AETHEER_JOB_RUNNING_TIMEOUT_SECONDS", 1800, minimum=30),
        "queue_metrics_sample_limit": _env_int("AETHEER_QUEUE_METRICS_SAMPLE_LIMIT", 500, minimum=10),
    }


def _queue_metrics_snapshot_safe() -> dict[str, Any]:
    try:
        payload = collect_queue_metrics_snapshot().model_dump()
        payload["available"] = True
        return payload
    except Exception as exc:
        logger.warning("Queue observability snapshot unavailable: %s", exc)
        return {
            "available": False,
            "error": "queue metrics unavailable",
        }


def _emit_request_log_event(
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    latency_ms: float,
    client_id: str,
    api_role: str,
    rejected: bool,
    error: str | None = None,
) -> None:
    event: dict[str, Any] = {
        "event": "http_request",
        "request_id": request_id,
        "method": method,
        "path": path,
        "status_code": int(status_code),
        "latency_ms": round(max(0.0, float(latency_ms)), 3),
        "client_id": client_id,
        "api_role": api_role,
        "instance_id": _instance_id,
        "rejected": rejected,
    }
    if error:
        event["error"] = str(error)[:300]

    logger.log(
        _request_log_level(int(status_code)),
        "http_request %s %s -> %s in %.3fms",
        method,
        path,
        int(status_code),
        round(max(0.0, float(latency_ms)), 3),
        extra={"event": event},
    )


def _post_alert_webhook(alert: dict[str, Any]) -> None:
    if not _alert_webhook_url:
        return

    payload = {
        "event": "runtime_alert",
        "instance_id": _instance_id,
        "alert": alert,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _alert_webhook_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "AetheerAI-Observability/2.1",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=_alert_hook_timeout_seconds) as response:
            status_code = int(getattr(response, "status", response.getcode()))
        if status_code >= 300:
            logger.warning(
                "Runtime alert webhook returned non-2xx status=%s",
                status_code,
                extra={"event": {"event": "runtime_alert_hook", "status_code": status_code}},
            )
    except Exception as exc:
        logger.error(
            "Runtime alert webhook delivery failed: %s",
            exc,
            exc_info=True,
            extra={"event": {"event": "runtime_alert_hook", "error": str(exc)[:300]}},
        )


def _dispatch_runtime_alert_if_needed() -> None:
    alert = _runtime.evaluate_alerts(uptime_seconds=time.time() - _boot_time)
    if alert is None:
        return

    provider, model = _runtime_active_provider_model()
    alert["runtime"] = {
        "provider": provider,
        "model": model,
    }
    reason_codes = [str(item.get("code", "")) for item in alert.get("reasons", [])]
    logger.warning(
        "runtime_alert_triggered severity=%s reasons=%s",
        alert.get("severity", "warning"),
        ",".join(code for code in reason_codes if code),
        extra={"event": {"event": "runtime_alert", "alert": alert}},
    )

    if _alert_webhook_url:
        threading.Thread(
            target=_post_alert_webhook,
            args=(dict(alert),),
            daemon=True,
            name="aetheer-alert-hook",
        ).start()


def _run_nlp(action: str, text: str, labels=None, question: str = "", max_length: int = 150, target_lang: str = "en") -> str:
    from tools.nlp_tool import nlp_tool
    return nlp_tool(
        action=action,
        text=text,
        labels=labels,
        question=question,
        max_length=max_length,
        target_lang=target_lang,
    )


def _run_vision(
    action: str,
    image_path: str = "",
    image_url: str = "",
    image_b64: str = "",
    question: str = "",
    provider: str = "",
) -> str:
    from tools.vision_tool import vision_tool
    return vision_tool(
        action=action,
        image_path=image_path,
        image_url=image_url,
        image_b64=image_b64,
        question=question,
        provider=provider,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _sqlite_log_handler

    logger.info("AetheerAI API startup")
    try:
        init_db()
    except Exception as _init_exc:
        logger.error("init_db failed — DB may be unavailable: %s", _init_exc)

    if _alert_webhook_url:
        logger.info("Runtime alert webhook configured")

    if _sqlite_log_handler is None:
        _sqlite_log_handler = _SQLiteLogHandler(level=logging.WARNING)
        logging.getLogger().addHandler(_sqlite_log_handler)

    if _eager_kernel_boot_enabled():
        _get_ceo()
        # Wire governance runtime into app state for API endpoints
        if _kernel is not None and hasattr(_kernel, "governance_runtime"):
            app.state.governance = _kernel.governance_runtime
            logger.info("Governance runtime attached to app state.")
    else:
        logger.info("Skipping eager kernel boot (serverless runtime detected)")
    yield

    if _sqlite_log_handler is not None:
        logging.getLogger().removeHandler(_sqlite_log_handler)
        _sqlite_log_handler = None

    logger.info("AetheerAI API shutdown")


_API_DESCRIPTION = """
## AetheerAI REST API — v2.1

**AetheerAI** is an autonomous multi-agent AI Operating System.  
This API exposes the full runtime: submit high-level goals, manage agents,
stream live progress, chat directly with the LLM, inspect memory, and save/restore snapshots.

---

### Authentication

All endpoints (except `/`, `/docs`, `/redoc`, `/api/health`, and `/ui/*`) require
a bearer token from `POST /api/auth/login`.

```
Authorization: Bearer <jwt-token>
```

On first login, users must configure their customer Supabase credentials via:

- `GET /api/auth/setup/sql` (returns SQL bootstrap script)
- `PUT /api/auth/setup/supabase` (stores customer Supabase details in AetheerAI Supabase)

After setup, data writes are mirrored to the customer's Supabase project.

---

### Tag groups

| Tag | What it covers |
|-----|----------------|
| **System** | Health check, runtime status, audit logs |
| **Goals** | Submit goals, poll progress, real-time SSE stream |
| **Projects** | Alias routes for Goals (backward-compatible) |
| **Agents** | Create / list / run / delete specialist agents |
| **Chat** | Direct single-turn or multi-turn LLM conversation |
| **Collaboration** | Multi-agent round-table sessions |
| **Memory** | Inspect and delete keys from the agent memory store |
| **State** | Save and restore full agent + memory snapshots |

---

### Real-time streaming

Two live-progress transports are available for any running goal:

| Transport | URL pattern | Notes |
|-----------|-------------|-------|
| **Server-Sent Events** | `GET /api/goals/{id}/stream` | Works with `EventSource`, curl `-N`, Postman |
| **WebSocket** | `ws://host/ws/goals/{id}` | Bidirectional; ideal for React / mobile |

Both emit incremental JSON diffs every ~800 ms and close with a terminal `done` event.
"""

_TAGS_METADATA = [
    {
        "name": "System",
        "description": "Health check, runtime status, and audit log endpoints. "
                       "Health is public; most system endpoints require login.",
    },
    {
        "name": "Goals",
        "description": "Submit a high-level goal and let the CEO agent decompose it "
                       "into tasks, assign specialist sub-agents, and execute them. "
                       "Poll status or subscribe to live SSE/WebSocket progress.",
    },
    {
        "name": "Projects",
        "description": "Backward-compatible aliases for the Goals endpoints. "
                       "Identical behaviour — use Goals for new integrations.",
    },
    {
        "name": "Agents",
        "description": "Create, list, run individual tasks on, and delete "
                       "specialist AI agents. Supports both manual configuration "
                       "and AI-designed agents via `/api/agents/design`.",
    },
    {
        "name": "Chat",
        "description": "Direct single-turn or multi-turn conversation with the "
                       "configured LLM. No CEO planning or agent orchestration — "
                       "just a raw chat completion.",
    },
    {
        "name": "Collaboration",
        "description": "Run structured multi-agent round-table sessions where "
                       "multiple agents debate, refine, and synthesise a shared answer.",
    },
    {
        "name": "Memory",
        "description": "Read and delete keys from the agent memory store. "
                       "Supports multiple namespaces (default: `global`).",
    },
    {
        "name": "State",
        "description": "Save the current agent roster + global memory to a JSON "
                       "snapshot, list snapshots, restore from a snapshot, or delete one. "
                       "Snapshots are stored at `AetheerAI/memory/snapshots/`.",
    },
    {
        "name": "UseCases",
        "description": "Discover and run packaged workflow templates with structured inputs/outputs.",
    },
    {
        "name": "Inference",
        "description": "Low-level prediction endpoint for direct model calls with optional overrides.",
    },
    {
        "name": "Integrations",
        "description": "Inbound/outbound external provider routes such as Meta webhook callbacks.",
    },
    {
        "name": "Tasks",
        "description": "Execute one-off tasks directly against a named agent or the base AI adapter.",
    },
]

app = FastAPI(
    title="AetheerAI API",
    description=_API_DESCRIPTION,
    version="2.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=_TAGS_METADATA,
    contact={
        "name": "TecBunny / AetheerAI",
        "url": "https://github.com/your-org/AetheerAI",
        "email": "support@aetheerai.dev",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    lifespan=lifespan,
)

app.include_router(auth_router)
app.include_router(db_router)
app.include_router(predict_router)
app.include_router(reports_router)
app.include_router(product_router)
app.include_router(queue_router)
app.include_router(meta_webhook_router)
app.include_router(payu_webhook_router)

# ── Governance API (operator controls for all 5 risk areas) ────────────────
from api.governance_api import router as governance_router
app.include_router(governance_router)

# ── Telemetry API (BLOCKER 3 — decision-grade observability) ───────────────
from api.telemetry_router import router as telemetry_router
app.include_router(telemetry_router)

# ── Mission / Goal Orchestration API (BLOCKER 6) ───────────────────────────
from api.goal_router import router as goal_router
app.include_router(goal_router)

# Serve built-in Web UI static files
_UI_DIR = Path(__file__).resolve().parents[1] / "ui"
if _UI_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_UI_DIR)), name="ui")

origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")
    if o.strip()
]
allow_all_origins = "*" in origins
if allow_all_origins:
    logger.warning(
        "CORS_ORIGINS includes '*'; credentials are disabled until explicit origins are configured."
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["http://localhost:3000", "http://localhost:8000"],
    allow_credentials=not allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    GZipMiddleware,
    minimum_size=_env_int("AETHEER_GZIP_MIN_BYTES", 1024, minimum=256),
)


# ── Security headers middleware ───────────────────────────────────────────────
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        host = (request.headers.get("host") or "").split(":")[0]
        if host not in ("localhost", "127.0.0.1", "0.0.0.0", ""):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

app.add_middleware(_SecurityHeadersMiddleware)


# ── v2 routers: planning, scheduling, risk, lifecycle ─────────────────────────
from api.routes_v2 import router as _v2_router  # noqa: E402
app.include_router(_v2_router)


# ── Kill switch endpoints (admin only) ────────────────────────────────────────
from api.auth import get_current_user, require_admin  # noqa: E402
from api.database import User, get_db  # noqa: E402

_admin_router = APIRouter(prefix="/api/admin", tags=["Admin"])


@_admin_router.get("/kill-switch", summary="Check kill switch status")
def get_kill_switch_status(admin: User = Depends(require_admin)):
    return {"active": _kill_switch_active}


@_admin_router.post("/kill-switch", summary="Activate kill switch — block all new goals and cancel running ones")
def activate_kill_switch(admin: User = Depends(require_admin)):
    global _kill_switch_active
    with _kill_switch_lock:
        _kill_switch_active = True
    cancelled = 0
    with _projects_lock:
        for project in _projects.values():
            if project.get("status") in {"pending", "running"}:
                project["status"] = "cancelled"
                project["error"] = "Cancelled by admin kill switch"
                cancelled += 1
    logger.warning("Kill switch activated by admin user_id=%s — cancelled %d projects", admin.id, cancelled)
    return {"active": True, "cancelled_projects": cancelled}


@_admin_router.delete("/kill-switch", summary="Deactivate kill switch — re-enable goal submissions")
def deactivate_kill_switch(admin: User = Depends(require_admin)):
    global _kill_switch_active
    with _kill_switch_lock:
        _kill_switch_active = False
    logger.info("Kill switch deactivated by admin user_id=%s", admin.id)
    return {"active": False}


app.include_router(_admin_router)


def _is_public_path(path: str) -> bool:
    if path in {
        "/",
        "/favicon.ico",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/health",
        "/api/ready",
        "/api/metrics",
        "/status",
        "/api/meta/webhook",
        "/api/payu/success",
        "/api/payu/failure",
    }:
        return True
    if path.startswith("/api/payu/"):
        return True
    if path.startswith("/ui"):
        return True
    if path.startswith("/api/auth"):
        return True
    return False


def _role_allows(role: str, required_role: str) -> bool:
    current = _API_ROLE_ORDER.get(str(role).strip().lower(), 0)
    required = _API_ROLE_ORDER.get(str(required_role).strip().lower(), 99)
    return current >= required


def _client_rate_limit_id(request: Request) -> str:
    ip = ""
    if _trust_proxy_headers():
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0].strip()

    if not ip:
        ip = request.client.host if request.client else "unknown"
    return f"ip:{ip}"


def _allow_request_under_rate_limit(client_id: str) -> tuple[bool, int]:
    return _runtime.allow_request(client_id)


async def _authorize_websocket(websocket: WebSocket, required_role: str = "user") -> bool:
    if _login_required():
        token = (
            _extract_bearer_token(websocket.headers.get("Authorization"))
            or websocket.query_params.get("token")
            or websocket.query_params.get("access_token")
        )
        if not token:
            await websocket.accept()
            await websocket.close(code=1008, reason="Login required")
            return False

        db: Session | None = None
        try:
            db = SessionLocal()
            user = authenticate_bearer_token(token, db)
        except Exception:
            if db is not None:
                db.close()
            await websocket.accept()
            await websocket.close(code=1008, reason="Unauthorized websocket")
            return False
        finally:
            if db is not None:
                db.close()

        if _enforce_customer_supabase_setup() and not user.is_admin:
            try:
                configured = is_customer_supabase_configured(int(user.id))
            except Exception:
                configured = False
            if not configured:
                await websocket.accept()
                await websocket.close(code=1008, reason="Customer Supabase setup required")
                return False

        role = "admin" if user.is_admin else "user"
        if not _role_allows(role, required_role):
            await websocket.accept()
            await websocket.close(code=1008, reason="Insufficient role")
            return False

        websocket.state.api_role = role
        websocket.state.current_user_id = int(user.id)
        websocket.state.current_username = str(user.username)
        return True

    # No API key fallback - require JWT authentication
    await websocket.accept()
    await websocket.close(code=1008, reason="Authentication required")
    return False


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    path = request.url.path
    method = request.method.upper()
    client_id = _client_rate_limit_id(request)
    request_id = (request.headers.get("X-Request-ID") or "").strip() or uuid.uuid4().hex
    request.state.request_id = request_id

    def _build_rejection(status_code: int, error: str, retry_after: int = 0) -> JSONResponse:
        elapsed_ms = round((time.perf_counter() - start_perf) * 1000.0, 3)
        _runtime.record_rejected_request(
            method=method,
            path=path,
            status_code=status_code,
            latency_ms=elapsed_ms,
            request_id=request_id,
            client_id=client_id,
            error=error,
        )
        _emit_request_log_event(
            request_id=request_id,
            method=method,
            path=path,
            status_code=status_code,
            latency_ms=elapsed_ms,
            client_id=client_id,
            api_role=getattr(request.state, "api_role", "unknown"),
            rejected=True,
            error=error,
        )
        _dispatch_runtime_alert_if_needed()
        payload: dict[str, Any] = {"success": False, "error": error}
        headers = {
            "X-Request-ID": request_id,
            "X-Instance-ID": _instance_id,
        }
        if retry_after > 0:
            headers["Retry-After"] = str(retry_after)
        return JSONResponse(status_code=status_code, content=payload, headers=headers)

    start_perf = time.perf_counter()
    user_context_tokens = None

    if _is_public_path(path):
        request.state.api_role = "public"
    else:
        if _login_required():
            auth_db: Session | None = None
            try:
                auth_db = SessionLocal()
                auth_user = resolve_bearer_user_from_request(request, auth_db)
            except HTTPException as exc:
                if auth_db is not None:
                    auth_db.close()
                return _build_rejection(exc.status_code, str(exc.detail))
            except Exception:
                if auth_db is not None:
                    auth_db.close()
                return _build_rejection(401, "Unauthorized")
            finally:
                if auth_db is not None:
                    auth_db.close()

            request.state.current_user_id = int(auth_user.id)
            request.state.current_username = str(auth_user.username)
            request.state.api_role = "admin" if bool(auth_user.is_admin) else "writer"

            if _enforce_customer_supabase_setup() and not bool(auth_user.is_admin):
                try:
                    configured = is_customer_supabase_configured(int(auth_user.id))
                except Exception as exc:
                    logger.warning("Customer Supabase setup check failed for user=%s: %s", auth_user.id, exc)
                    configured = False
                if not configured:
                    return _build_rejection(
                        428,
                        "Customer Supabase setup required. Use /api/auth/setup/sql and /api/auth/setup/supabase.",
                    )

            user_context_tokens = set_request_user(int(auth_user.id), str(auth_user.username))
            request.state.api_role = "admin" if auth_user.is_admin else "user"
            try:
                _apply_user_ai_runtime_preference(request)
            except Exception as exc:
                logger.warning("Unable to apply user AI runtime preference for user=%s: %s", auth_user.id, exc)
        else:
            # No API key fallback - require JWT authentication
            return _build_rejection(401, "Authentication required")

    should_throttle = path not in _non_throttled_paths
    acquired_slot = False
    if should_throttle:
        allowed, retry_after = _allow_request_under_rate_limit(client_id)
        if not allowed:
            return _build_rejection(429, "Rate limit exceeded", retry_after=retry_after or 60)

        try:
            await asyncio.wait_for(
                _request_slots.acquire(),
                timeout=_runtime.config.request_queue_timeout_seconds,
            )
            acquired_slot = True
        except TimeoutError:
            return _build_rejection(503, "Server busy: request queue timeout")

    _runtime.begin_request()
    status_code = 500
    failure_text: str | None = None
    response = None
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as exc:
        failure_text = str(exc)
        _attempt_runtime_failover(exc)
        raise
    finally:
        elapsed_ms = round((time.perf_counter() - start_perf) * 1000.0, 3)
        _runtime.end_request(
            method=method,
            path=path,
            status_code=status_code,
            latency_ms=elapsed_ms,
            request_id=request_id,
            client_id=client_id,
            error=failure_text,
        )
        _emit_request_log_event(
            request_id=request_id,
            method=method,
            path=path,
            status_code=status_code,
            latency_ms=elapsed_ms,
            client_id=client_id,
            api_role=getattr(request.state, "api_role", "unknown"),
            rejected=False,
            error=failure_text,
        )
        _dispatch_runtime_alert_if_needed()
        if acquired_slot:
            _request_slots.release()
        if user_context_tokens is not None:
            reset_request_user(user_context_tokens)

    if response is not None:
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Instance-ID"] = _instance_id
    return response


def custom_openapi() -> dict[str, Any]:
    """Inject security schemes so Swagger documents authenticated calls."""
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=_TAGS_METADATA,
    )
    components = schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "Bearer token returned by POST /api/auth/login.",
    }
    security_schemes["ApiKeyHeader"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "Legacy API-key auth (used only when AETHEER_REQUIRE_LOGIN=false).",
    }

    # Protected routes are gated by middleware even if they do not declare a
    # per-route dependency, so annotate them for generated API clients.
    for path, path_item in (schema.get("paths") or {}).items():
        if _is_public_path(str(path)):
            continue
        if not isinstance(path_item, dict):
            continue

        for method, operation in path_item.items():
            if str(method).lower() not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                continue
            if not isinstance(operation, dict):
                continue

            security = operation.get("security")
            desired = [{"BearerAuth": []}] if _login_required() else [{"ApiKeyHeader": []}]
            if isinstance(security, list):
                for item in desired:
                    if item not in security:
                        security.append(item)
            else:
                operation["security"] = desired

    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi


@app.get("/", include_in_schema=False)
def serve_ui():
    """Serve the built-in Web UI."""
    index = _UI_DIR / "index.html"
    if index.is_file():
        return FileResponse(str(index), media_type="text/html")
    return JSONResponse({"message": "AetheerAI API is running. See /docs for endpoints."})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled API error: %s", exc, exc_info=True)
    _attempt_runtime_failover(exc)
    request_id = getattr(request.state, "request_id", "") or "unknown"
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "Internal server error"},
        headers={
            "X-Request-ID": request_id,
            "X-Instance-ID": _instance_id,
        },
    )



class APIResponse(BaseModel):
    """Standard envelope returned by every endpoint."""

    success: bool = Field(True, description="`true` on success, `false` on error.")
    data: Any = Field(None, description="Payload — shape varies per endpoint (see individual docs).")
    error: str | None = Field(None, description="Human-readable error detail when `success` is false.")
    message: str | None = Field(None, description="Optional informational message.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "data": {"id": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "status": "completed"},
                "error": None,
                "message": None,
            }
        }
    }


class AIRuntimeRequest(BaseModel):
    """Payload to switch the active runtime AI provider/model."""

    provider: str = Field(
        ...,
        min_length=1,
        description="Target provider name. Must be one of SUPPORTED_PROVIDERS.",
    )
    model: str | None = Field(
        default=None,
        description="Optional model override. When omitted, provider default model is used.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "provider": "github",
                "model": "gpt-4.1",
            }
        }
    }


class GoalRequest(BaseModel):
    """Payload to submit a new goal or project."""

    name: str = Field(
        ..., min_length=1, max_length=200,
        description="Short human-readable project name (used in listings).",
    )
    goal: str = Field(
        ..., min_length=1,
        description="Free-text description of what AetheerAI should accomplish. "
                    "Be as specific as you like — the CEO agent will decompose it.",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional key/value context injected into the CEO planning prompt.",
    )
    max_cost_usd: float | None = Field(
        None, ge=0,
        description="Hard spending cap in USD. Overrides the server default when set.",
    )
    max_runtime_seconds: int | None = Field(
        None, ge=1,
        description="Hard wall-clock timeout in seconds. Overrides the server default when set.",
    )
    background: bool = Field(
        False,
        description="When `true` the goal is queued and the API returns immediately with a "
                    "pending ID. Poll `GET /api/goals/{id}` or stream `/api/goals/{id}/stream`.",
    )
    parallel: bool = Field(
        True,
        description="Run independent sub-tasks in parallel threads (recommended).",
    )
    collaboration_mode: bool = Field(
        False,
        description="Enable multi-agent collaboration debate on the final plan.",
    )
    offline_local_mode: bool = Field(
        False,
        description="Force this goal to run on the local/offline provider defined by "
                    "`AETHEER_OFFLINE_PROVIDER` / `AETHEER_OFFLINE_MODEL`.",
    )
    fast_mode_collaboration: bool = Field(
        False,
        description="Use a lightweight collaboration strategy optimised for speed.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "saas-landing-page",
                "goal": "Build a professional SaaS landing page for TaskFlow with hero section, pricing table, and FAQ.",
                "background": True,
                "parallel": True,
                "max_cost_usd": 5.0,
                "max_runtime_seconds": 300,
            }
        }
    }


class AgentRequest(BaseModel):
    """Payload to manually configure a new agent."""

    name: str = Field(
        ..., min_length=1, max_length=100,
        description="Unique agent identifier. Used as the agent's key in the registry.",
    )
    role: str | None = Field(
        None,
        description="Short human-readable role title, e.g. `\"Senior Python Developer\"`.",
    )
    tools: list[str] = Field(
        default_factory=list,
        description="List of tool names to enable for this agent, e.g. `[\"web_search\", \"code_executor\"]`.",
    )
    skills: list[str] = Field(default_factory=list, description="Skill catalog entries to attach.")
    objectives: list[str] = Field(default_factory=list, description="Standing objectives baked into the system prompt.")
    permissions: list[str] = Field(default_factory=list, description="Explicit permission grants (e.g. `read_files`).")
    permission_level: int = Field(
        default=1, ge=0, le=5,
        description="Numeric permission tier (0 = read-only, 5 = full system access). Default: 1.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "frontend-dev",
                "role": "Senior Frontend Developer",
                "tools": ["web_search", "code_executor", "file_writer"],
                "permission_level": 2,
            }
        }
    }


class AgentRunRequest(BaseModel):
    """Single task to execute on an existing agent."""

    task: str = Field(
        ..., min_length=1,
        description="Free-text task description. The agent will execute it and return the result.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {"task": "Write a Python function that validates an email address using regex."}
        }
    }


class AgentDesignRequest(BaseModel):
    """Let the AI design a new agent from a role description and goal."""

    name: str = Field(
        ..., min_length=1, max_length=100,
        description="Unique agent identifier to register the newly designed agent under.",
    )
    role_description: str = Field(
        ..., min_length=1, max_length=200,
        description="One-sentence description of the agent's expertise, "
                    "e.g. `\"Senior data analyst specialising in Python and pandas\"`.",
    )
    goal: str = Field(
        ..., min_length=1,
        description="What this agent should accomplish. Used to select tools and draft objectives.",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional extra context passed to the AI designer prompt.",
    )
    permission_level: int | None = Field(
        default=None, ge=1, le=5,
        description="Override the AI-suggested permission level (1–5).",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "data-analyst",
                "role_description": "Senior data analyst specialising in Python and pandas",
                "goal": "Analyse Q1 sales data and produce an executive summary with charts.",
                "permission_level": 2,
            }
        }
    }


class CollaborationRequest(BaseModel):
    """Start a multi-agent collaboration session."""

    goal: str = Field(
        ..., min_length=1,
        description="Topic or question the agents should collectively solve.",
    )
    team_name: str | None = Field(
        None,
        description="Name of a pre-defined team. Mutually exclusive with `agent_names`.",
    )
    agent_names: list[str] = Field(
        default_factory=list,
        description="Explicit list of agent names to invite. Mutually exclusive with `team_name`.",
    )
    rounds: int = Field(
        default=2, ge=1, le=6,
        description="Number of debate/refinement rounds (1–6). More rounds → better synthesis, more tokens.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "goal": "What is the best architecture for a real-time notification system at 1 M users/day?",
                "agent_names": ["backend-dev", "devops-engineer", "data-analyst"],
                "rounds": 3,
            }
        }
    }


class ChatRequest(BaseModel):
    """Single-turn or multi-turn direct LLM chat (no CEO planning)."""

    message: str = Field(
        ..., min_length=1,
        description="The user message to send to the LLM.",
    )
    system_prompt: str | None = Field(
        None,
        description="Optional system prompt to prepend. Overrides the default assistant persona.",
    )
    history: list[dict[str, str]] = Field(
        default_factory=list,
        description="Prior conversation turns as `[{\"role\": \"user\"|\"assistant\", \"content\": \"...\"}]`. "
                    "Last 20 entries are sent.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "message": "Explain the difference between REST and GraphQL in 3 bullet points.",
                "history": [
                    {"role": "user", "content": "Hi, I'm building an API."},
                    {"role": "assistant", "content": "Great! What kind of API are you building?"},
                ],
            }
        }
    }


class UseCaseRunRequest(BaseModel):
    """Run a packaged use case with simple key/value inputs."""

    inputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Input payload for the selected use case.",
    )


def _serialize_project_result(project_id: str, name: str, result: "ProjectResult") -> dict[str, Any]:
    total = max(1, result.total_tasks)
    return {
        "id": project_id,
        "workflow_id": result.workflow_id,
        "name": name,
        "goal": result.goal,
        "status": result.status,
        "plan_summary": result.final_summary,
        "spent_usd": result.spent_usd,
        "progress": {
            "completed": result.completed_tasks,
            "failed": result.failed_tasks,
            "total": result.total_tasks,
            "percent": round((result.completed_tasks / total) * 100.0, 2),
        },
        "tasks": [
            {
                "task_id": t.task_id,
                "index": t.index,
                "title": t.title,
                "description": t.description,
                "agent_type": t.agent_type,
                "role_description": t.role_description,
                "priority": t.priority,
                "depends_on": t.depends_on,
                "require_approval": t.require_approval,
                "status": t.status,
                "result": t.result,
                "error": t.error,
                "attempts": t.attempts,
            }
            for t in result.tasks
        ],
        "total_tasks": result.total_tasks,
        "completed_tasks": result.completed_tasks,
        "failed_tasks": result.failed_tasks,
        "elapsed_seconds": result.elapsed_seconds,
        "replanned": result.replanned,
        "events": result.events,
    }


def _as_utc_datetime(value: Any) -> datetime.datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.datetime.utcfromtimestamp(value)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.datetime.fromisoformat(text)
        except ValueError:
            return None
    return None


def _connection_state_value(connection: Any | None, name: str) -> Any:
    state = getattr(connection, "state", None)
    return getattr(state, name, None) if state is not None else None


def _connection_user_id(connection: Any | None) -> int | None:
    raw = _connection_state_value(connection, "current_user_id")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _connection_username(connection: Any | None) -> str | None:
    raw = _connection_state_value(connection, "current_username")
    text = str(raw or "").strip()
    return text or None


def _connection_is_admin(connection: Any | None) -> bool:
    role = str(_connection_state_value(connection, "api_role") or "").strip().lower()
    return role == "admin"


def _project_owner_user_id(project: dict[str, Any] | None) -> int | None:
    raw = (project or {}).get("owner_user_id")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _connection_can_access_project(
    connection: Any | None,
    project: dict[str, Any] | None,
    *,
    _internal: bool = False,
) -> bool:
    if _connection_is_admin(connection):
        return True

    current_user_id = _connection_user_id(connection)
    if current_user_id is None:
        # Deny by default when user identity is unknown.
        # Internal lookups (no request context) may pass _internal=True.
        return _internal

    owner_user_id = _project_owner_user_id(project)
    return owner_user_id is None or owner_user_id == current_user_id


def _adapter_usage_snapshot(kernel: "AetheerAiKernel") -> tuple[int, int, int]:
    usage = getattr(getattr(kernel, "ai_adapter", None), "usage", {}) or {}
    try:
        prompt_tokens = max(0, int(usage.get("prompt_tokens", 0) or 0))
        completion_tokens = max(0, int(usage.get("completion_tokens", 0) or 0))
        total_tokens = max(0, int(usage.get("total_tokens", 0) or 0))
    except Exception:
        return 0, 0, 0
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens
    return prompt_tokens, completion_tokens, total_tokens


def _record_request_log_best_effort(
    request: Request,
    *,
    event_type: str,
    action: str,
    status: str,
    provider: str | None = None,
    model: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    owner_user_id = _connection_user_id(request)
    if owner_user_id is None:
        return
    try:
        record_user_analytics_log_best_effort(
            user_id=owner_user_id,
            username=_connection_username(request),
            event_type=event_type,
            action=action,
            status=status,
            provider=provider,
            model=model,
            metadata=metadata,
        )
    except Exception:
        # Best-effort analytics should not break API requests.
        return


def _record_request_ai_usage_best_effort(
    request: Request,
    *,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    metadata: dict[str, Any] | None = None,
) -> None:
    owner_user_id = _connection_user_id(request)
    if owner_user_id is None:
        return
    if max(int(prompt_tokens or 0), int(completion_tokens or 0), int(total_tokens or 0)) <= 0:
        return
    try:
        record_user_token_usage_best_effort(
            user_id=owner_user_id,
            username=_connection_username(request),
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            metadata=metadata,
        )
    except Exception:
        return


def _persist_project_to_db(
    project_id: str,
    name: str,
    payload: dict[str, Any],
    *,
    owner_user_id: int | None = None,
) -> None:
    db = SessionLocal()
    try:
        resolved_owner_user_id = owner_user_id
        if resolved_owner_user_id is None:
            resolved_owner_user_id = _project_owner_user_id(payload)

        row = db.query(GoalRun).filter(GoalRun.id == project_id).first()
        if row is None:
            row = GoalRun(
                id=project_id,
                owner_user_id=resolved_owner_user_id,
                name=name,
                goal=str(payload.get("goal", "")),
            )
            db.add(row)

        if resolved_owner_user_id is not None:
            row.owner_user_id = resolved_owner_user_id
        row.name = name
        row.goal = str(payload.get("goal", ""))
        row.status = str(payload.get("status", "pending"))
        row.plan_summary = payload.get("plan_summary")
        row.total_tasks = int(payload.get("total_tasks") or 0)
        row.completed_tasks = int(payload.get("completed_tasks") or 0)
        row.failed_tasks = int(payload.get("failed_tasks") or 0)
        row.spent_usd = payload.get("spent_usd")
        row.elapsed_seconds = payload.get("elapsed_seconds")
        row.error = payload.get("error")
        row.replanned = bool(payload.get("replanned", False))
        row.started_at = _as_utc_datetime(payload.get("started_at"))

        if row.status in {"completed", "failed", "cancelled"}:
            row.completed_at = _as_utc_datetime(payload.get("completed_at")) or datetime.datetime.utcnow()

        db.query(Task).filter(Task.goal_id == project_id).delete(synchronize_session=False)
        for task in payload.get("tasks", []):
            db.add(
                Task(
                    owner_user_id=resolved_owner_user_id,
                    task_uuid=task.get("task_id"),
                    goal_id=project_id,
                    task_index=int(task.get("index") or 0),
                    title=str(task.get("title") or ""),
                    description=task.get("description"),
                    agent_type=task.get("agent_type"),
                    role_description=task.get("role_description"),
                    priority=int(task.get("priority") or 1),
                    depends_on=task.get("depends_on") or [],
                    require_approval=bool(task.get("require_approval", False)),
                    status=str(task.get("status") or "pending"),
                    result=task.get("result"),
                    error=task.get("error"),
                    attempts=int(task.get("attempts") or 0),
                )
            )

        db.commit()
    finally:
        db.close()


def _read_audit_logs(limit: int = 200) -> list[dict[str, Any]]:
    root = Path(__file__).resolve().parents[1]
    log_path = root / "memory" / "audit_log.jsonl"
    if not log_path.exists() or limit <= 0:
        return []

    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []

    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"raw": line})
    return out


def _find_task(task_id: str) -> dict[str, Any] | None:
    with _projects_lock:
        projects = list(_projects.values())

    for project in projects:
        if not _connection_can_access_project(None, project, _internal=True):
            continue
        for task in project.get("tasks", []):
            if str(task.get("task_id", "")) == task_id:
                return {
                    "project_id": project.get("id"),
                    "project_name": project.get("name"),
                    **task,
                }
    return None


async def _submit_goal(
    req: GoalRequest,
    background_tasks: BackgroundTasks,
    request: Request | None = None,
) -> APIResponse:
    if _kill_switch_active:
        raise HTTPException(
            status_code=503,
            detail="Kill switch is active — all new goal submissions are blocked. Contact an admin.",
        )
    if _env_bool("VERCEL", False) and _env_bool("AETHEER_DISABLE_VERCEL_DIRECT_GOALS", True):
        raise HTTPException(
            status_code=503,
            detail="Direct goal execution is disabled on Vercel. Submit via POST /api/queue/jobs.",
        )

    try:
        max_active = max(1, int((os.getenv("AETHER_MAX_CONCURRENT_GOALS") or "8").strip()))
    except ValueError:
        max_active = 8

    with _projects_lock:
        active_count = sum(1 for p in _projects.values() if p.get("status") in {"pending", "running"})
    if active_count >= max_active:
        raise HTTPException(
            status_code=429,
            detail=f"Too many active goals ({active_count}/{max_active}). Try again shortly.",
        )

    project_id = str(uuid.uuid4())
    owner_user_id = _connection_user_id(request)
    owner_username = _connection_username(request)
    with _projects_lock:
        _projects[project_id] = {
            "id": project_id,
            "name": req.name,
            "goal": req.goal,
            "status": "pending",
            "started_at": time.time(),
            "offline_local_mode": req.offline_local_mode,
            "fast_mode_collaboration": req.fast_mode_collaboration,
            "owner_user_id": owner_user_id,
            "owner_username": owner_username,
        }

    def _run_goal() -> None:
        request_user_tokens = None
        if owner_user_id is not None:
            request_user_tokens = set_request_user(owner_user_id, owner_username)
        try:
            if req.offline_local_mode:
                target_provider = os.getenv("AETHEER_OFFLINE_PROVIDER", "ollama").strip().lower() or "ollama"
                target_model = os.getenv("AETHEER_OFFLINE_MODEL", "llama3.2:1b").strip() or "llama3.2:1b"
                ceo = _build_goal_ceo(
                    provider=target_provider,
                    model=target_model,
                    max_cost_usd=req.max_cost_usd,
                    max_runtime_seconds=req.max_runtime_seconds,
                )
                logger.info(
                    "Goal %s running in isolated offline_local_mode runtime using %s/%s",
                    project_id,
                    target_provider,
                    target_model,
                )
            else:
                ceo = _build_goal_ceo(
                    max_cost_usd=req.max_cost_usd,
                    max_runtime_seconds=req.max_runtime_seconds,
                )

            with _projects_lock:
                _projects[project_id]["status"] = "running"

            result = ceo.run(
                req.goal,
                context=req.context or None,
                parallel=req.parallel,
                collaboration_mode=req.collaboration_mode,
                offline_local_mode=req.offline_local_mode,
                fast_mode_collaboration=req.fast_mode_collaboration,
            )
            _record_runtime_ai_success()
            payload = _serialize_project_result(project_id, req.name, result)
            with _projects_lock:
                payload["started_at"] = _projects.get(project_id, {}).get("started_at")
            with _projects_lock:
                _projects[project_id].update(payload)
                _projects[project_id]["status"] = result.status
                snapshot = dict(_projects[project_id])

            try:
                _persist_project_to_db(
                    project_id,
                    req.name,
                    snapshot,
                    owner_user_id=owner_user_id,
                )
            except Exception as db_exc:
                logger.warning("Goal %s persisted in-memory but DB write failed: %s", project_id, db_exc)
        except Exception as exc:
            logger.error("Goal %s failed: %s", project_id, exc, exc_info=True)
            _attempt_runtime_failover(exc)
            with _projects_lock:
                _projects[project_id]["status"] = "failed"
                _projects[project_id]["error"] = str(exc)
                snapshot = dict(_projects[project_id])

            try:
                _persist_project_to_db(
                    project_id,
                    req.name,
                    snapshot,
                    owner_user_id=owner_user_id,
                )
            except Exception as db_exc:
                logger.warning("Goal %s failure state could not be persisted: %s", project_id, db_exc)
        finally:
            if request_user_tokens is not None:
                reset_request_user(request_user_tokens)

    if req.background:
        background_tasks.add_task(_run_goal)
        return APIResponse(
            data={"id": project_id, "status": "pending"},
            message="Goal accepted. Poll /api/goals/{id} for updates.",
        )

    _run_goal()
    with _projects_lock:
        return APIResponse(data=dict(_projects[project_id]))


@app.get("/api/health", tags=["System"], response_model=APIResponse,
         summary="Health check",
         description="Lightweight liveness probe. Always returns `200 OK` with the active "
                     "provider and model. **No login required.**")
def health_check():
    def _payload() -> dict[str, Any]:
        provider, model = _runtime_active_provider_model()
        metrics = _runtime.metrics_snapshot()
        return {
            "status": "ok",
            "version": "2.1.0",
            "instance_id": _instance_id,
            "provider": provider,
            "model": model,
            "offline_local_mode_default": os.getenv("AETHEER_OFFLINE_LOCAL_MODE", "false").strip().lower()
            in {"1", "true", "yes", "on"},
            "fast_mode_collaboration_default": os.getenv("AETHEER_FAST_MODE_COLLABORATION", "false")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
            "offline_provider": os.getenv("AETHEER_OFFLINE_PROVIDER", "ollama"),
            "offline_model": os.getenv("AETHEER_OFFLINE_MODEL", "llama3.2:1b"),
            "supported_providers": list(SUPPORTED_PROVIDERS),
            "load": {
                "in_flight": metrics["in_flight"],
                "max_concurrent_requests": metrics["max_concurrent_requests"],
                "avg_latency_ms": metrics["avg_latency_ms"],
                "rejected_total": metrics["rejected_total"],
            },
        }

    return APIResponse(data=_cached_payload("health", _health_cache_ttl, _payload))


@app.get("/api/ready", tags=["System"], response_model=APIResponse,
         summary="Readiness probe",
         description="Deep readiness probe for load balancers and orchestrators. Returns 503 when degraded.")
def readiness_check():
    ready = True
    checks: dict[str, Any] = {}

    db = None
    try:
        db = SessionLocal()
        db.connection().exec_driver_sql("SELECT 1")
        checks["database"] = "ok"
    except Exception as exc:
        ready = False
        checks["database"] = f"error: {exc}"
    finally:
        if db is not None:
            db.close()

    if _readiness_requires_kernel_boot():
        try:
            _get_kernel()
            checks["kernel"] = "ok"
        except Exception as exc:
            ready = False
            checks["kernel"] = f"error: {exc}"
    else:
        checks["kernel"] = "skipped (serverless mode)"

    metrics = _runtime.metrics_snapshot()
    saturation = metrics["in_flight"] / max(1, metrics["max_concurrent_requests"])
    checks["load_saturation"] = round(saturation, 3)
    if saturation >= 0.95:
        ready = False
        checks["load"] = "saturated"

    provider, model = _runtime_active_provider_model()
    payload = {
        "status": "ready" if ready else "degraded",
        "instance_id": _instance_id,
        "checks": checks,
        "load": metrics,
        "failover": _runtime.failover_state(provider, model),
    }

    response = APIResponse(
        success=ready,
        data=payload,
        error=None if ready else "Service is not ready",
    )
    if ready:
        return response
    return JSONResponse(status_code=503, content=response.model_dump())


@app.get("/api/metrics", tags=["System"], include_in_schema=False)
def metrics_prometheus():
    runtime_payload = _runtime.prometheus_text(
        instance_id=_instance_id,
        uptime_seconds=time.time() - _boot_time,
    )
    queue_payload = queue_metrics_prometheus_text(instance_id=_instance_id)
    payload = f"{runtime_payload}{queue_payload}"
    return PlainTextResponse(payload, media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/api/system/status", tags=["System"], response_model=APIResponse,
         summary="Full runtime status",
         description="Returns live counters for projects, agents, tools, and memory keys. "
                     "Use this as a rich dashboard data source.")
def system_status(request: Request):
    def _payload() -> dict[str, Any]:
        provider, model = _runtime_active_provider_model()
        with _projects_lock:
            projects = list(_projects.values())
        visible_projects = [p for p in projects if _connection_can_access_project(request, p)]

        runtime_metrics = _runtime.metrics_snapshot()
        kernel = None
        kernel_error = None
        try:
            kernel = _get_kernel()
        except Exception as exc:
            kernel_error = str(exc)
            logger.warning("system_status kernel unavailable: %s", exc)

        if kernel is None:
            agents_registered = 0
            tools_registered = 0
            memory_keys = 0
            collaboration_sessions = 0
        else:
            agents_registered = len(kernel.registry.list_names())
            tools_registered = len(kernel.tool_manager.list_tools())
            memory_keys = len(kernel.memory.keys())
            collaboration_sessions = len(kernel.collaboration_sessions(limit=1000))

        return {
            "status": "ok" if kernel is not None else "degraded",
            "instance_id": _instance_id,
            "uptime_seconds": round(time.time() - _boot_time, 3),
            "provider": provider,
            "model": model,
            "offline_local_mode_default": os.getenv("AETHEER_OFFLINE_LOCAL_MODE", "false").strip().lower()
            in {"1", "true", "yes", "on"},
            "fast_mode_collaboration_default": os.getenv("AETHEER_FAST_MODE_COLLABORATION", "false")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
            "offline_provider": os.getenv("AETHEER_OFFLINE_PROVIDER", "ollama"),
            "offline_model": os.getenv("AETHEER_OFFLINE_MODEL", "llama3.2:1b"),
            "supported_providers": list(SUPPORTED_PROVIDERS),
            "projects": {
                "total": len(visible_projects),
                "running": len([p for p in visible_projects if p.get("status") == "running"]),
                "completed": len([p for p in visible_projects if p.get("status") == "completed"]),
                "partial": len([p for p in visible_projects if p.get("status") == "partial"]),
                "failed": len([p for p in visible_projects if p.get("status") == "failed"]),
                "cancelled": len([p for p in visible_projects if p.get("status") == "cancelled"]),
            },
            "kernel_available": kernel is not None,
            "kernel_error": kernel_error,
            "agents_registered": agents_registered,
            "tools_registered": tools_registered,
            "memory_keys": memory_keys,
            "collaboration_sessions": collaboration_sessions,
            "runtime_metrics": runtime_metrics,
            "observability": {
                "settings": _observability_settings(),
                "recent_alerts": _runtime.recent_alerts(limit=5),
            },
            "queue_monitoring": _queue_metrics_snapshot_safe(),
            "failover": _runtime.failover_state(provider, model),
        }

    if _connection_is_admin(request) or _connection_user_id(request) is None:
        return APIResponse(data=_cached_payload("system_status", _status_cache_ttl, _payload))
    return APIResponse(data=_payload())


@app.post(
    "/api/system/ai/runtime",
    tags=["System"],
    response_model=APIResponse,
    summary="Switch active AI runtime",
    description="Hot-switch the in-memory AI provider/model for this running server process. "
    "Requires an admin user session. Changes are not persisted across restarts.",
)
def switch_ai_runtime(req: AIRuntimeRequest, request: Request):
    role = (getattr(request.state, "api_role", "") or "").lower()
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")

    target_provider = (req.provider or "").strip().lower()
    supported = set(SUPPORTED_PROVIDERS)
    if target_provider not in supported:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider '{target_provider}'. Supported providers: {sorted(supported)}",
        )

    target_model = (req.model or "").strip() or None

    persisted = False
    persist_error: str | None = None

    try:
        with _ai_switch_lock:
            if _kernel is not None:
                _kernel.ai_adapter.switch(target_provider, target_model)
                active_provider = _kernel.ai_adapter.provider
                active_model = _kernel.ai_adapter.model
            else:
                active_provider = target_provider
                active_model = target_model or AIAdapter._default_model(target_provider)
            _response_cache.invalidate("health")
            _response_cache.invalidate("system_status")

            user_id = _connection_user_id(request)
            username = str(getattr(request.state, "current_username", "") or "")
            if user_id is not None and username:
                try:
                    existing = get_customer_ai_api_settings(user_id=user_id, include_secret=True) or {}
                    existing_provider = str(existing.get("provider") or "").strip().lower() if isinstance(existing, dict) else ""
                    carry_api_key = (existing.get("api_key") if isinstance(existing, dict) and existing_provider == active_provider else None)
                    carry_base_url = (existing.get("base_url") if isinstance(existing, dict) and existing_provider == active_provider else None)
                    save_customer_ai_api_settings(
                        user_id=user_id,
                        username=username,
                        provider=active_provider,
                        model=active_model,
                        api_key=carry_api_key,
                        base_url=carry_base_url,
                        extra=(existing.get("extra") if isinstance(existing, dict) else {}),
                    )
                    kernel = _get_kernel()
                    kernel.ai_adapter.configure_provider(
                        active_provider,
                        api_key=carry_api_key,
                        base_url=carry_base_url,
                    )
                    persisted = True
                    _invalidate_user_ai_runtime_preference(user_id)
                except Exception as exc:
                    persist_error = str(exc)
                    logger.warning("Runtime switch persistence skipped: %s", exc)
                finally:
                    with _user_ai_runtime_cache_lock:
                        _user_ai_runtime_overrides[int(user_id)] = (
                            time.time(),
                            active_provider,
                            active_model,
                            locals().get("carry_api_key"),
                            locals().get("carry_base_url"),
                        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Runtime switch failed: {exc}")

    message = "Runtime AI settings updated for this server process."
    if persisted:
        message = "Runtime AI settings updated and persisted to customer Supabase."
    elif persist_error:
        message = "Runtime AI settings updated for this server process. Persistent save is unavailable."

    return APIResponse(
        data={
            "provider": active_provider,
            "model": active_model,
            "supported_providers": list(SUPPORTED_PROVIDERS),
            "persisted": persisted,
            "persist_error": persist_error,
        },
        message=message,
    )


@app.get("/api/system/traces", tags=["System"], response_model=APIResponse,
         summary="Recent request traces",
         description="Returns the most recent HTTP request traces captured by middleware instrumentation.")
def system_traces(request: Request, limit: int = 100):
    if not _connection_is_admin(request):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    safe_limit = max(1, min(limit, 500))
    return APIResponse(data={"instance_id": _instance_id, "traces": _runtime.recent_traces(safe_limit)})


@app.get("/api/system/failover", tags=["System"], response_model=APIResponse,
         summary="Failover state",
         description="Returns automatic failover configuration and current activation state.")
def system_failover_state(request: Request):
    if not _connection_is_admin(request):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    provider, model = _runtime_active_provider_model()
    return APIResponse(data=_runtime.failover_state(provider, model))


@app.get("/api/system/observability", tags=["System"], response_model=APIResponse,
         summary="Observability state",
         description="Returns observability thresholds, monitoring hook status, and recent alerts.")
def system_observability(request: Request, limit: int = 25):
    if not _connection_is_admin(request):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    safe_limit = max(1, min(limit, 50))
    return APIResponse(
        data={
            "instance_id": _instance_id,
            "runtime_metrics": _runtime.metrics_snapshot(),
            "queue_metrics": _queue_metrics_snapshot_safe(),
            "settings": _observability_settings(),
            "recent_alerts": _runtime.recent_alerts(limit=safe_limit),
        }
    )


@app.get("/api/logs", tags=["System"], response_model=APIResponse,
         summary="Audit log",
         description="Returns the last `limit` entries from the append-only JSONL audit log "
                     "(`memory/audit_log.jsonl`). Every tool call and agent action is recorded here.")
def list_logs(limit: int = 200):
    limit = max(1, min(limit, 1000))
    return APIResponse(data=_read_audit_logs(limit=limit))


@app.get("/api/usecases", tags=["UseCases"], response_model=APIResponse,
         summary="List packaged use cases",
         description="Returns all packaged workflow templates available in this runtime.")
def list_usecases():
    """List all packaged use-case workflows available in this runtime."""
    return APIResponse(data=use_case_registry.list())


@app.post("/api/usecases/{usecase_name}/run", tags=["UseCases"], response_model=APIResponse,
          summary="Run a packaged use case",
          description="Executes a named use-case workflow with provided inputs and returns summary, "
                      "structured outputs, and generated file paths.")
def run_usecase(usecase_name: str, req: UseCaseRunRequest):
    """Run a named packaged use case and return files/summary."""
    kernel = _get_kernel()
    result = use_case_registry.run(usecase_name, req.inputs or {}, kernel)
    if not result.success:
        return APIResponse(success=False, error=result.error or "Use case failed.")
    payload = {
        "summary": result.summary,
        "outputs": result.outputs,
        "output_files": [
            {"label": label, "path": path} for (label, path) in result.output_files
        ],
    }
    return APIResponse(data=payload)


@app.post("/api/goals", tags=["Goals"], response_model=APIResponse, status_code=201,
          summary="Submit a goal",
          description="""
The primary entry point. Send a high-level natural-language goal and AetheerAI will:

1. **Plan** — the CEO agent decomposes the goal into ordered sub-tasks.
2. **Assign** — specialist agents (Developer, Researcher, Marketer, Ops, …) are assigned.
3. **Execute** — tasks run in parallel (if enabled) with HITL approval gates for risky actions.
4. **Deliver** — a consolidated summary and per-task results are returned.

Set `background: true` to return immediately with a goal ID and stream progress via
`GET /api/goals/{id}/stream` (SSE) or `ws://host/ws/goals/{id}` (WebSocket).
""")
async def submit_goal(req: GoalRequest, background_tasks: BackgroundTasks, request: Request):
    return await _submit_goal(req, background_tasks, request)


@app.get("/api/goals", tags=["Goals"], response_model=APIResponse,
         summary="List all goals",
         description="Returns all goals sorted newest-first. Each item includes `status`, "
                     "`progress`, `spent_usd`, and a task breakdown.")
def list_goals(request: Request):
    with _projects_lock:
        items = [p for p in _projects.values() if _connection_can_access_project(request, p)]
        items = sorted(items, key=lambda p: p.get("started_at", 0), reverse=True)
        return APIResponse(data=list(items))


@app.get("/api/goals/{goal_id}", tags=["Goals"], response_model=APIResponse,
         summary="Get goal by ID",
         description="Returns the full goal record including all task results, cost, "
                     "elapsed time, and the CEO's plan summary.")
def get_goal(goal_id: str, request: Request):
    with _projects_lock:
        project = _projects.get(goal_id)
        if project is None or not _connection_can_access_project(request, project):
            raise HTTPException(status_code=404, detail=f"Goal '{goal_id}' not found.")
        return APIResponse(data=dict(project))


@app.get("/api/goals/{goal_id}/tasks", tags=["Goals"], response_model=APIResponse,
         summary="List tasks for a goal",
         description="Returns the ordered list of sub-tasks created by the CEO agent. "
                     "Each task has `status`, `result`, `agent_type`, `priority`, and `attempts`.")
def get_goal_tasks(goal_id: str, request: Request):
    with _projects_lock:
        project = _projects.get(goal_id)
        if project is None or not _connection_can_access_project(request, project):
            raise HTTPException(status_code=404, detail=f"Goal '{goal_id}' not found.")
        return APIResponse(data=project.get("tasks", []))


@app.get("/api/tasks/{task_id}", tags=["Goals"], response_model=APIResponse,
         summary="Get a single task",
         description="Look up one sub-task by its UUID across all goals.")
def get_task(task_id: str, request: Request):
    with _projects_lock:
        projects = list(_projects.values())

    task = None
    for project in projects:
        if not _connection_can_access_project(request, project):
            continue
        for candidate in project.get("tasks", []):
            if str(candidate.get("task_id", "")) == task_id:
                task = {
                    "project_id": project.get("id"),
                    "project_name": project.get("name"),
                    **candidate,
                }
                break
        if task is not None:
            break
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
    return APIResponse(data=task)


@app.post("/api/collaborations", tags=["Collaboration"], response_model=APIResponse, status_code=201,
          summary="Start a collaboration session",
          description="""
Runs a structured multi-agent round-table debate. Each agent produces an answer, then
agents read each other's responses and refine their own over `rounds` iterations.
The session result contains every agent's final answer plus a synthesised conclusion.

Provide **either** `team_name` (a pre-defined team) **or** `agent_names` (an explicit list)—not both.
""")
def run_collaboration(req: CollaborationRequest):
    kernel = _get_kernel()

    if req.team_name and req.agent_names:
        raise HTTPException(
            status_code=400,
            detail="Provide either team_name or agent_names, not both.",
        )
    if not req.team_name and not req.agent_names:
        raise HTTPException(
            status_code=400,
            detail="Provide team_name or at least one agent name.",
        )

    try:
        payload = kernel.collaborate(
            goal=req.goal,
            team_name=req.team_name,
            agent_names=req.agent_names or None,
            rounds=req.rounds,
        )
        _record_runtime_ai_success()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _attempt_runtime_failover(exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return APIResponse(data=payload)


@app.get("/api/collaborations", tags=["Collaboration"], response_model=APIResponse,
         summary="List collaboration sessions",
         description="Returns the most recent `limit` collaboration sessions (default: 50).")
def list_collaborations(limit: int = 50):
    try:
        kernel = _get_kernel()
        data = kernel.collaboration_sessions(limit=limit)
        if not isinstance(data, list):
            data = []
        return APIResponse(data=data)
    except Exception as exc:
        logger.warning("Collaborations list degraded: %s", exc)
        return APIResponse(data=[], message="Collaborations are temporarily unavailable. Please try again shortly.")


@app.get("/api/collaborations/{session_id}", tags=["Collaboration"], response_model=APIResponse,
         summary="Get collaboration session",
         description="Returns the full record for a specific collaboration session by ID.")
def get_collaboration(session_id: str):
    kernel = _get_kernel()
    session = kernel.collaboration_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Collaboration session '{session_id}' not found.")
    return APIResponse(data=session)


# Backward-compatible project routes.
@app.post("/api/projects", tags=["Projects"], response_model=APIResponse, status_code=201,
          summary="Submit a project (alias for POST /api/goals)",
          description="Identical to `POST /api/goals`. Provided for backward-compatibility.")
async def create_project(req: GoalRequest, background_tasks: BackgroundTasks, request: Request):
    return await _submit_goal(req, background_tasks, request)


@app.get("/api/projects", tags=["Projects"], response_model=APIResponse,
         summary="List projects (alias for GET /api/goals)",
         description="Identical to `GET /api/goals`.")
def list_projects(request: Request):
    return list_goals(request)


@app.get("/api/projects/{project_id}", tags=["Projects"], response_model=APIResponse,
         summary="Get project by ID (alias)",
         description="Identical to `GET /api/goals/{goal_id}`.")
def get_project(project_id: str, request: Request):
    return get_goal(project_id, request)


@app.delete("/api/projects/{project_id}", tags=["Projects"], response_model=APIResponse,
            summary="Delete a project",
            description="Removes the project record from the in-memory store. "
                        "This does not cancel a currently running goal.")
def delete_project(project_id: str, request: Request):
    with _projects_lock:
        project = _projects.get(project_id)
        if project is None or not _connection_can_access_project(request, project):
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")
        del _projects[project_id]
    return APIResponse(message=f"Project '{project_id}' deleted.")


@app.post("/api/agents", tags=["Agents"], response_model=APIResponse, status_code=201,
          summary="Create an agent",
          description="""
Manually configure and register a new specialist agent.

For AI-designed agents (where the LLM selects tools and writes objectives for you),
use `POST /api/agents/design` instead.

Returns 409 if an agent with the same name already exists.
""")
def create_agent(req: AgentRequest, request: Request):
    kernel = _get_kernel()
    if kernel.registry.get(req.name):
        raise HTTPException(status_code=409, detail=f"Agent '{req.name}' already exists.")

    try:
        agent = kernel.factory.create(
            name=req.name,
            role=req.role,
            tools=req.tools or None,
            skills=req.skills or None,
            objectives=req.objectives or None,
            permissions=req.permissions or None,
            permission_level=req.permission_level,
        )
        if hasattr(agent, "attach_runtime"):
            agent.attach_runtime(
                ai_adapter=kernel.ai_adapter,
                workflow_engine=kernel.workflow_engine,
                tool_manager=kernel.tool_manager,
            )
        if hasattr(agent, "attach_memory"):
            agent.attach_memory(kernel.memory)

        owner_user_id = _connection_user_id(request)
        if owner_user_id is not None:
            try:
                agent_dict = agent.to_dict() if hasattr(agent, "to_dict") else {}
                record_user_agent_profile_best_effort(
                    user_id=owner_user_id,
                    username=_connection_username(request),
                    agent_name=str((agent_dict or {}).get("name") or req.name),
                    role=str((agent_dict or {}).get("role") or req.role),
                    source="manual",
                    tools=(agent_dict or {}).get("tools") or req.tools or [],
                    skills=(agent_dict or {}).get("skills") or req.skills or [],
                    objectives=(agent_dict or {}).get("objectives") or req.objectives or [],
                    permission_level=(agent_dict or {}).get("permission_level") if isinstance(agent_dict, dict) else req.permission_level,
                    metadata={"endpoint": "/api/agents", "mode": "manual"},
                )
            except Exception:
                pass

        return APIResponse(data=agent.to_dict(), message=f"Agent '{req.name}' created.")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/agents/design", tags=["Agents"], response_model=APIResponse, status_code=201,
          summary="AI-design an agent",
          description="""
Use the LLM to automatically design a specialist agent. Provide a `role_description` and a `goal`;
the AI will select the best tools, write standing objectives, and configure permissions.

The resulting agent is registered and ready to use immediately.
""")
def design_agent(req: AgentDesignRequest, request: Request):
    kernel = _get_kernel()
    if kernel.registry.get(req.name):
        raise HTTPException(status_code=409, detail=f"Agent '{req.name}' already exists.")

    try:
        agent = kernel.factory.design_agent(
            name=req.name,
            role_description=req.role_description,
            goal=req.goal,
            context=req.context,
            permission_level=req.permission_level,
        )
        _record_runtime_ai_success()
        if hasattr(agent, "attach_runtime"):
            agent.attach_runtime(
                ai_adapter=kernel.ai_adapter,
                workflow_engine=kernel.workflow_engine,
                tool_manager=kernel.tool_manager,
            )
        if hasattr(agent, "attach_memory"):
            agent.attach_memory(kernel.memory)

        owner_user_id = _connection_user_id(request)
        if owner_user_id is not None:
            try:
                agent_dict = agent.to_dict() if hasattr(agent, "to_dict") else {}
                record_user_agent_profile_best_effort(
                    user_id=owner_user_id,
                    username=_connection_username(request),
                    agent_name=str((agent_dict or {}).get("name") or req.name),
                    role=str((agent_dict or {}).get("role") or req.role_description),
                    source="ai_design",
                    tools=(agent_dict or {}).get("tools") or [],
                    skills=(agent_dict or {}).get("skills") or [],
                    objectives=(agent_dict or {}).get("objectives") or [],
                    permission_level=(agent_dict or {}).get("permission_level") if isinstance(agent_dict, dict) else req.permission_level,
                    metadata={
                        "endpoint": "/api/agents/design",
                        "goal_chars": len(str(req.goal or "")),
                        "context_keys": len(req.context or {}),
                    },
                )
            except Exception:
                pass

        return APIResponse(data=agent.to_dict(), message=f"Agent '{req.name}' designed and created.")
    except Exception as exc:
        _attempt_runtime_failover(exc)
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/agents", tags=["Agents"], response_model=APIResponse,
         summary="List agents",
         description="Returns all registered agents with their tools, skills, objectives, and permission level.")
def list_agents():
    try:
        kernel = _get_kernel()
        data = kernel.registry.list_all()
        if not isinstance(data, list):
            data = []
        return APIResponse(data=data)
    except Exception as exc:
        logger.warning("Agents list degraded: %s", exc)
        return APIResponse(data=[], message="Agents are temporarily unavailable. Please try again shortly.")


@app.get("/api/agents/{agent_name}", tags=["Agents"], response_model=APIResponse,
         summary="Get agent details",
         description="Returns the full configuration of a named agent.")
def get_agent(agent_name: str):
    kernel = _get_kernel()
    agent = kernel.registry.get(agent_name)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found.")
    return APIResponse(data=agent.to_dict())


@app.delete("/api/agents/{agent_name}", tags=["Agents"], response_model=APIResponse,
            summary="Delete an agent",
            description="Removes the agent from the registry. Running tasks are not interrupted.")
def delete_agent(agent_name: str):
    kernel = _get_kernel()
    if not kernel.registry.remove(agent_name):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found.")
    return APIResponse(message=f"Agent '{agent_name}' removed.")


@app.post("/api/agents/{agent_name}/run", tags=["Agents"], response_model=APIResponse,
          summary="Run a task on an agent",
          description="""
Execute a single free-text task on a named agent and return the result synchronously.

The agent's configured tools and memory are available during execution.
For long-running tasks consider using `POST /api/goals` and polling instead.
""")
def run_agent_task(agent_name: str, req: AgentRunRequest, request: Request):
    kernel = _get_kernel()
    agent = kernel.registry.get(agent_name)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found.")

    try:
        if hasattr(agent, "attach_runtime"):
            agent.attach_runtime(
                ai_adapter=kernel.ai_adapter,
                workflow_engine=kernel.workflow_engine,
                tool_manager=kernel.tool_manager,
            )
        if hasattr(agent, "attach_memory"):
            agent.attach_memory(kernel.memory)

        result = agent.execute_task(req.task)
        _record_runtime_ai_success()

        provider = str(getattr(kernel.ai_adapter, "provider", "") or "")
        model = str(getattr(kernel.ai_adapter, "model", "") or "")
        prompt_tokens, completion_tokens, total_tokens = _adapter_usage_snapshot(kernel)
        _record_request_ai_usage_best_effort(
            request,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            metadata={
                "endpoint": "/api/agents/{agent_name}/run",
                "agent_name": agent_name,
                "task_chars": len(str(req.task or "")),
            },
        )
        _record_request_log_best_effort(
            request,
            event_type="agent",
            action="run_task",
            status="ok",
            provider=provider,
            model=model,
            metadata={
                "agent_name": agent_name,
                "task_chars": len(str(req.task or "")),
                "result_chars": len(str(result or "")),
            },
        )
        return APIResponse(data={"agent": agent_name, "result": result})
    except Exception as exc:
        _record_request_log_best_effort(
            request,
            event_type="agent",
            action="run_task",
            status="error",
            metadata={
                "agent_name": agent_name,
                "task_chars": len(str(req.task or "")),
                "error": str(exc)[:220],
            },
        )
        _attempt_runtime_failover(exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/chat", tags=["Chat"], response_model=APIResponse,
          summary="Direct LLM chat",
          description="""
Send a message directly to the configured LLM and get a reply.

No CEO planning, no agents, no tools — just a raw chat completion.
Optional `history` lets you maintain multi-turn context (last 20 turns are sent).
Optional `system_prompt` overrides the default assistant persona for this request.
""")
def chat(req: ChatRequest, request: Request):
    messages: list[dict[str, str]] = []
    if req.system_prompt:
        messages.append({"role": "system", "content": req.system_prompt})
    messages.extend(req.history[-20:])
    messages.append({"role": "user", "content": req.message})

    try:
        kernel = _get_kernel()
        reply = kernel.ai_adapter.chat(messages)
        _record_runtime_ai_success()

        provider = str(getattr(kernel.ai_adapter, "provider", "") or "")
        model = str(getattr(kernel.ai_adapter, "model", "") or "")
        prompt_tokens, completion_tokens, total_tokens = _adapter_usage_snapshot(kernel)
        _record_request_ai_usage_best_effort(
            request,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            metadata={
                "endpoint": "/api/chat",
                "message_chars": len(str(req.message or "")),
                "history_turns": len(req.history or []),
            },
        )
        _record_request_log_best_effort(
            request,
            event_type="chat",
            action="chat_request",
            status="ok",
            provider=provider,
            model=model,
            metadata={
                "message_chars": len(str(req.message or "")),
                "history_turns": len(req.history or []),
                "reply_chars": len(str(reply or "")),
            },
        )
        return APIResponse(data={"reply": reply})
    except Exception as exc:
        try:
            _record_request_log_best_effort(
                request,
                event_type="chat",
                action="chat_request",
                status="error",
                metadata={
                    "message_chars": len(str(req.message or "")),
                    "history_turns": len(req.history or []),
                    "error": str(exc)[:220],
                },
            )
        except Exception:
            pass
        try:
            _attempt_runtime_failover(exc)
        except Exception as failover_exc:
            logger.warning("Chat failover hook failed: %s", failover_exc)
        logger.warning("Chat degraded response due to adapter error: %s", exc)
        return APIResponse(
            data={
                "reply": (
                    "I am temporarily unable to reach the configured AI provider. "
                    "Please try again in a moment or check Settings -> AI Configuration."
                )
            },
            message="Chat response returned in degraded mode.",
        )


@app.get("/api/memory", tags=["Memory"], response_model=APIResponse,
         summary="Read memory namespace",
         description="Returns all key/value pairs in the specified memory namespace. "
                     "Default namespace is `global`. Agent-specific namespaces use the agent name.")
def get_memory(namespace: str = "global"):
    try:
        kernel = _get_kernel()
        data = kernel.memory.all(namespace=namespace)
    except Exception as exc:
        logger.warning("Memory read degraded for namespace '%s': %s", namespace, exc)
        return APIResponse(data={}, message="Memory is temporarily unavailable for this namespace.")
    return APIResponse(data=data)


@app.delete("/api/memory/{key}", tags=["Memory"], response_model=APIResponse,
            summary="Delete a memory key",
            description="Deletes a single key from the specified namespace. "
                        "Returns 404 if the key does not exist.")
def delete_memory_key(key: str, namespace: str = "global"):
    kernel = _get_kernel()
    try:
        deleted = kernel.memory.delete(key, namespace=namespace)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found in namespace '{namespace}'.")
    return APIResponse(message=f"Key '{key}' deleted from namespace '{namespace}'.")


# ── Snapshots directory ─────────────────────────────────────────────────────
def _resolve_snapshots_dir() -> Path:
    explicit_dir = (os.getenv("AETHEER_SNAPSHOTS_DIR") or "").strip()
    if explicit_dir:
        return Path(explicit_dir)

    if _is_serverless_runtime():
        return Path(tempfile.gettempdir()) / "aetheer_snapshots"

    return Path(__file__).resolve().parents[1] / "memory" / "snapshots"


def _ensure_snapshots_dir() -> Path:
    preferred = _resolve_snapshots_dir()
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "aetheer_snapshots"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


_SNAPSHOTS_DIR = _ensure_snapshots_dir()


# ── Real-time: SSE stream for goal progress ──────────────────────────────────
@app.get("/api/goals/{goal_id}/stream", tags=["Goals"], include_in_schema=True,
         summary="Live SSE stream",
         description="Server-Sent Events stream — pushes JSON progress diffs until the goal is terminal.")
async def stream_goal_sse(goal_id: str, request: Request):
    with _projects_lock:
        project = _projects.get(goal_id)
    if project is None or not _connection_can_access_project(request, project):
        raise HTTPException(status_code=404, detail=f"Goal '{goal_id}' not found.")

    async def _generate() -> AsyncGenerator[str, None]:
        last_sig: str | None = None
        while True:
            if await request.is_disconnected():
                break
            with _projects_lock:
                project = _projects.get(goal_id)
            if project is None:
                yield 'event: error\ndata: {"error": "Goal not found"}\n\n'
                break
            sig = f"{project.get('status')}:{project.get('completed_tasks',0)}:{project.get('total_tasks',0)}"
            if sig != last_sig:
                last_sig = sig
                payload = json.dumps({
                    "id": goal_id,
                    "status": project.get("status"),
                    "progress": project.get("progress", {}),
                    "completed_tasks": project.get("completed_tasks", 0),
                    "total_tasks": project.get("total_tasks", 0),
                    "failed_tasks": project.get("failed_tasks", 0),
                    "spent_usd": project.get("spent_usd", 0),
                    "plan_summary": project.get("plan_summary"),
                    "events": (project.get("events") or [])[-20:],
                })
                yield f"data: {payload}\n\n"
            if project.get("status") in ("completed", "failed", "partial", "cancelled"):
                status_val = project.get("status")
                yield f'event: done\ndata: {{"__done__": true, "status": "{status_val}"}}\n\n'
                break
            await asyncio.sleep(0.8)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ── Real-time: WebSocket stream for goal progress ────────────────────────────
@app.websocket("/ws/goals/{goal_id}")
async def ws_goal_stream(websocket: WebSocket, goal_id: str):
    """WebSocket — pushes goal progress diffs until the goal reaches a terminal state."""
    if not await _authorize_websocket(websocket, required_role="reader"):
        return

    with _projects_lock:
        project = _projects.get(goal_id)
    if project is None or not _connection_can_access_project(websocket, project):
        await websocket.accept()
        await websocket.close(code=1008, reason="Goal not found")
        return

    await websocket.accept()
    try:
        last_sig: str | None = None
        while True:
            with _projects_lock:
                project = _projects.get(goal_id)
            if project is None:
                await websocket.send_json({"error": "Goal not found"})
                break
            sig = f"{project.get('status')}:{project.get('completed_tasks',0)}:{project.get('total_tasks',0)}"
            if sig != last_sig:
                last_sig = sig
                await websocket.send_json({
                    "id": goal_id,
                    "status": project.get("status"),
                    "progress": project.get("progress", {}),
                    "completed_tasks": project.get("completed_tasks", 0),
                    "total_tasks": project.get("total_tasks", 0),
                    "failed_tasks": project.get("failed_tasks", 0),
                    "spent_usd": project.get("spent_usd", 0),
                    "plan_summary": project.get("plan_summary"),
                })
            if project.get("status") in ("completed", "failed", "partial", "cancelled"):
                await websocket.send_json({"__done__": True, "status": project.get("status")})
                break
            await asyncio.sleep(0.8)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ── State: save / load / list / delete snapshots ─────────────────────────────
class SaveStateRequest(BaseModel):
    name: str = Field(default="snapshot", min_length=1, max_length=60)

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "milestone_release_candidate",
            }
        }
    }


@app.post("/api/state/save", tags=["State"], response_model=APIResponse,
          summary="Save state snapshot",
          description="Serialise the current agent roster and global memory to a JSON file on disk.")
def save_state(req: SaveStateRequest):
    kernel = _get_kernel()
    provider, model = _resolve_ai_runtime()
    _SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c for c in req.name if c.isalnum() or c in "-_")[:50] or "snapshot"
    filename = f"{safe_name}_{ts}.json"
    filepath = _SNAPSHOTS_DIR / filename
    try:
        agents = kernel.registry.list_all()
        try:
            memory = kernel.memory.all(namespace="global")
        except Exception:
            memory = {}
        state = {
            "version": "2.0",
            "saved_at": time.time(),
            "name": safe_name,
            "agents": agents,
            "memory": memory,
            "provider": provider,
            "model": model,
        }
        filepath.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        return APIResponse(
            data={"filename": filename, "agents": len(agents), "memory_keys": len(memory)},
            message=f"State saved \u2192 {filename}",
        )
    except Exception as exc:
        logger.error("save_state failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/state/snapshots", tags=["State"], response_model=APIResponse,
         summary="List snapshots",
         description="List all available state snapshot files with metadata.")
def list_snapshots():
    _SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snapshots: list[dict] = []
    for f in sorted(_SNAPSHOTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))
            snapshots.append({
                "filename": f.name,
                "name": meta.get("name", f.stem),
                "saved_at": meta.get("saved_at"),
                "agent_count": len(meta.get("agents", [])),
                "memory_keys": len(meta.get("memory", {})),
                "provider": meta.get("provider"),
                "model": meta.get("model"),
                "version": meta.get("version"),
            })
        except Exception:
            snapshots.append({"filename": f.name, "name": f.stem, "saved_at": None})
    return APIResponse(data=snapshots)


@app.post("/api/state/load", tags=["State"], response_model=APIResponse,
          summary="Restore snapshot",
          description="Re-register agents from a named snapshot (existing agents are skipped).")
def load_state(filename: str):
    safe_filename = Path(filename).name
    if not safe_filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Filename must end with .json")
    filepath = _SNAPSHOTS_DIR / safe_filename
    if not filepath.is_file():
        raise HTTPException(status_code=404, detail=f"Snapshot '{safe_filename}' not found.")
    try:
        state = json.loads(filepath.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid or corrupt snapshot file.")
    kernel = _get_kernel()
    loaded = 0
    skipped = 0
    for agent_data in state.get("agents", []):
        name = agent_data.get("name")
        if not name:
            continue
        if kernel.registry.get(name):
            skipped += 1
            continue
        try:
            agent = kernel.factory.create(
                name=name,
                role=agent_data.get("role"),
                tools=agent_data.get("tools") or None,
                permission_level=agent_data.get("permission_level", 1),
            )
            if hasattr(agent, "attach_runtime"):
                agent.attach_runtime(
                    ai_adapter=kernel.ai_adapter,
                    workflow_engine=kernel.workflow_engine,
                    tool_manager=kernel.tool_manager,
                )
            if hasattr(agent, "attach_memory"):
                agent.attach_memory(kernel.memory)
            loaded += 1
        except Exception as exc:
            logger.warning("load_state: could not restore agent '%s': %s", name, exc)
    return APIResponse(
        data={"loaded_agents": loaded, "skipped_agents": skipped, "filename": safe_filename},
        message=f"Restored {loaded} agents from '{safe_filename}' ({skipped} already existed).",
    )


@app.delete("/api/state/snapshots/{filename}", tags=["State"], response_model=APIResponse,
            summary="Delete snapshot",
            description="Permanently delete a state snapshot file from disk.")
def delete_snapshot(filename: str):
    safe_filename = Path(filename).name
    if not safe_filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Filename must end with .json")
    filepath = _SNAPSHOTS_DIR / safe_filename
    if not filepath.is_file():
        raise HTTPException(status_code=404, detail=f"Snapshot '{safe_filename}' not found.")
    try:
        filepath.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return APIResponse(message=f"Snapshot '{safe_filename}' deleted.")


# ── Predict / Status / Task ────────────────────────────────────────────────


class PredictRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="The prompt to send to the AI model.")
    system_prompt: str | None = Field(default=None, description="Optional system-level instruction.")
    model: str | None = Field(default=None, description="Override the active model for this request.")
    provider: str | None = Field(default=None, description="Override the active provider for this request.")
    history: list[dict[str, str]] = Field(
        default_factory=list,
        description="Optional prior conversation turns [{role, content}, …].",
    )
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


class TaskRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="Short title for the task.")
    description: str = Field(..., min_length=1, description="Full task description / instructions.")
    agent: str | None = Field(
        default=None,
        description="Name of a registered agent to run the task. If omitted, the kernel AI adapter is used.",
    )
    context: dict[str, Any] = Field(default_factory=dict, description="Optional key/value context passed to the agent.")
    background: bool = Field(default=False, description="Return immediately with a task ID and run in background.")


class MLTrainRequest(BaseModel):
    model_name: str = Field(..., min_length=1, max_length=120, description="Unique model identifier.")
    task: str = Field(default="classification", description="classification | regression | clustering")
    algorithm: str = Field(default="auto", description="Training algorithm override, e.g. random_forest, logistic_regression.")
    features: list[Any] = Field(..., min_length=1, description="Training feature rows (text, numeric, or dict records).")
    labels: list[Any] | None = Field(default=None, description="Target values. Required for classification/regression.")
    test_size: float = Field(default=0.2, ge=0.05, le=0.5, description="Holdout split ratio.")
    n_clusters: int = Field(default=5, ge=2, le=100, description="Number of clusters for clustering tasks.")
    auto_save: bool = Field(default=True, description="Persist trained model to .pkl immediately.")


class MLPredictRequest(BaseModel):
    model_name: str = Field(..., min_length=1, max_length=120, description="Trained model identifier.")
    features: list[Any] = Field(..., min_length=1, description="Input feature rows for prediction.")
    include_probabilities: bool = Field(
        default=False,
        description="For classification models, include class probability distributions.",
    )


class NLPRequest(BaseModel):
    action: str = Field(default="sentiment", description="sentiment | ner | classify | summarize | qa | translate | embed")
    text: str = Field(..., min_length=1, description="Input text.")
    labels: list[str] = Field(default_factory=list, description="Candidate labels for classify action.")
    question: str = Field(default="", description="Question for qa action.")
    max_length: int = Field(default=150, ge=30, le=512, description="Summary max length.")
    target_lang: str = Field(default="en", description="Target language (ISO 639-1) for translate action.")


class VisionRequest(BaseModel):
    action: str = Field(default="describe", description="describe | extract | analyze | code_ui | audit")
    image_path: str = Field(default="", description="Local image path (inside project sandbox).")
    image_url: str = Field(default="", description="Public HTTPS image URL.")
    image_b64: str = Field(default="", description="Raw base64 image data or data URI.")
    question: str = Field(default="", description="Question for analyze action.")
    provider: str = Field(default="", description="Optional provider override: openai | anthropic | gemini")


@app.post("/predict", tags=["Inference"], response_model=APIResponse,
          summary="Run direct prediction",
          description="Send a prompt directly to the active provider/model and return a reply. "
                      "Useful for lightweight inference without goal orchestration.")
def predict(req: PredictRequest, background_tasks: BackgroundTasks):
    """Run a single-shot AI completion/chat prediction and return the model reply."""
    kernel = _get_kernel()
    adapter = kernel.ai_adapter
    using_override_adapter = bool(req.provider or req.model)
    response_provider = str(adapter.provider)
    response_model = str(adapter.model)

    # Build a request-scoped adapter when overrides are provided so shared runtime
    # state is not mutated across concurrent requests.
    if using_override_adapter:
        target_provider = (req.provider or response_provider).strip().lower()
        target_model = (req.model or response_model).strip()
        try:
            adapter = AIAdapter(provider=target_provider, model=target_model)
            response_provider = str(adapter.provider)
            response_model = str(adapter.model)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Provider/model override failed: {exc}")

    local_model = _get_local_predictor()
    local_result = local_model.predict(req.prompt)

    try:
        messages: list[dict[str, str]] = []
        if req.system_prompt:
            messages.append({"role": "system", "content": req.system_prompt})
        messages.extend(req.history[-20:])
        messages.append({"role": "user", "content": req.prompt})

        extra: dict[str, Any] = {}
        if req.max_tokens is not None:
            extra["max_tokens"] = req.max_tokens
        if req.temperature is not None:
            extra["temperature"] = req.temperature

        reply = adapter.chat(messages, **extra) if extra else adapter.chat(messages)
        _record_runtime_ai_success()

        return APIResponse(
            data={
                "reply": reply,
                "local_prediction": local_result,
                "provider": response_provider,
                "model": response_model,
                "prompt_length": len(req.prompt),
            }
        )
    except Exception as exc:
        # Keep /predict always usable, even without external AI credentials.
        if not using_override_adapter:
            _attempt_runtime_failover(exc)
        logger.warning("/predict cloud inference failed; returning local fallback: %s", exc)
        return APIResponse(
            data={
                "reply": local_result,
                "local_prediction": local_result,
                "provider": "local",
                "model": local_model.version,
                "prompt_length": len(req.prompt),
                "fallback": True,
            },
            message="Cloud model unavailable; returned local predictor result.",
        )


@app.post("/api/ml/train", tags=["Inference"], response_model=APIResponse,
          summary="Train an ML model",
          description="Train a local scikit-learn model (classification/regression/clustering) and persist it as .pkl.")
def ml_train(req: MLTrainRequest):
    try:
        engine = _get_ml_engine()
        report = engine.train(
            name=req.model_name,
            features=req.features,
            labels=req.labels,
            task=req.task,
            algorithm=req.algorithm,
            test_size=req.test_size,
            n_clusters=req.n_clusters,
            auto_save=req.auto_save,
        )
        return APIResponse(data=report, message=f"Model '{req.model_name}' trained successfully.")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ml/predict", tags=["Inference"], response_model=APIResponse,
          summary="Predict with a trained ML model",
          description="Run prediction through a trained .pkl model. Supports optional class probabilities.")
def ml_predict(req: MLPredictRequest):
    try:
        engine = _get_ml_engine()
        preds = engine.predict(req.model_name, req.features)
        payload: dict[str, Any] = {
            "model_name": req.model_name,
            "predictions": preds,
            "count": len(preds),
        }
        if req.include_probabilities:
            payload["probabilities"] = engine.predict_proba(req.model_name, req.features)
        return APIResponse(data=payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/ml/models", tags=["Inference"], response_model=APIResponse,
         summary="List trained ML models",
         description="Returns metadata for all trained models discovered in memory and on disk.")
def ml_models():
    try:
        engine = _get_ml_engine()
        return APIResponse(data=engine.list_models())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/api/ml/models/{model_name}", tags=["Inference"], response_model=APIResponse,
            summary="Delete a trained ML model",
            description="Deletes a model from memory and removes its .pkl/.meta files from disk.")
def ml_delete_model(model_name: str):
    try:
        engine = _get_ml_engine()
        if not engine.delete_model(model_name):
            raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found.")
        return APIResponse(message=f"Model '{model_name}' deleted.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/nlp", tags=["Inference"], response_model=APIResponse,
          summary="Run NLP inference",
          description="Run sentiment, NER, summarization, QA, translation, or embedding on text.")
def nlp_infer(req: NLPRequest):
    try:
        result = _run_nlp(
            action=req.action,
            text=req.text,
            labels=req.labels,
            question=req.question,
            max_length=req.max_length,
            target_lang=req.target_lang,
        )
        return APIResponse(data={"action": req.action, "result": result})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/vision", tags=["Inference"], response_model=APIResponse,
          summary="Run vision model inference",
          description="Analyze images via describe/OCR/QA/UI-code/audit modes using a vision-capable provider.")
def vision_infer(req: VisionRequest):
    try:
        result = _run_vision(
            action=req.action,
            image_path=req.image_path,
            image_url=req.image_url,
            image_b64=req.image_b64,
            question=req.question,
            provider=req.provider,
        )
        return APIResponse(data={"action": req.action, "result": result})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/status", tags=["System"], response_model=APIResponse,
         summary="Lightweight status",
         description="Compact service status endpoint with uptime and project/agent counters.")
def status():
    """Top-level service status — lightweight health + live counters."""
    try:
        def _payload() -> dict[str, Any]:
            kernel = _get_kernel()
            with _projects_lock:
                projects = list(_projects.values())

            running = [p for p in projects if p.get("status") == "running"]
            pending = [p for p in projects if p.get("status") == "pending"]
            done = [p for p in projects if p.get("status") == "completed"]
            failed = [p for p in projects if p.get("status") in {"failed", "cancelled"}]
            provider, model = _runtime_active_provider_model()

            return {
                "status": "ok",
                "version": "2.1.0",
                "instance_id": _instance_id,
                "uptime_seconds": round(time.time() - _boot_time, 3),
                "provider": provider,
                "model": model,
                "local_predictor": _get_local_predictor().version,
                "projects": {
                    "total": len(projects),
                    "running": len(running),
                    "pending": len(pending),
                    "completed": len(done),
                    "failed": len(failed),
                },
                "agents_registered": len(kernel.registry.list_names()),
                "tools_registered": len(kernel.tool_manager.list_tools()),
                "runtime_metrics": _runtime.metrics_snapshot(),
                "observability": {
                    "settings": _observability_settings(),
                    "recent_alerts": _runtime.recent_alerts(limit=3),
                },
                "failover": _runtime.failover_state(provider, model),
            }

        return APIResponse(data=_cached_payload("status", _status_cache_ttl, _payload))
    except Exception as exc:
        logger.error("Status check error: %s", exc, exc_info=True)
        return APIResponse(
            success=False,
            data={"status": "degraded"},
            error=str(exc),
        )


@app.post("/task", tags=["Tasks"], response_model=APIResponse, status_code=201,
          summary="Create and run one task",
          description="Execute one task on a named agent or directly on the AI adapter. "
                      "Supports background mode for async execution.")
async def create_task(req: TaskRequest, background_tasks: BackgroundTasks, request: Request):
    """Submit a task for execution by a named agent or the kernel AI adapter.

    - If *agent* is provided, the named agent's ``execute_task`` method is called.
    - Otherwise, the prompt is sent directly to the AI adapter (like ``/predict``).
    - Set *background=true* to get an immediate task-ID response and run async.
    """
    task_id = str(uuid.uuid4())
    owner_user_id = _connection_user_id(request)
    owner_username = _connection_username(request)

    def _run_task() -> dict[str, Any]:
        kernel = _get_kernel()
        try:
            if req.agent:
                agent = kernel.registry.get(req.agent)
                if agent is None:
                    raise ValueError(f"Agent '{req.agent}' not found.")
                if hasattr(agent, "attach_runtime"):
                    agent.attach_runtime(
                        ai_adapter=kernel.ai_adapter,
                        workflow_engine=kernel.workflow_engine,
                        tool_manager=kernel.tool_manager,
                    )
                if hasattr(agent, "attach_memory"):
                    agent.attach_memory(kernel.memory)
                result = agent.execute_task(req.description)
            else:
                messages = [{"role": "user", "content": req.description}]
                result = kernel.ai_adapter.chat(messages)
            _record_runtime_ai_success()
        except Exception as exc:
            _attempt_runtime_failover(exc)
            raise

        return {
            "task_id": task_id,
            "title": req.title,
            "agent": req.agent,
            "result": str(result),
            "status": "completed",
        }

    if req.background:
        # Store placeholder and run in background
        with _projects_lock:
            _projects[task_id] = {
                "id": task_id,
                "name": req.title,
                "goal": req.description,
                "status": "pending",
                "started_at": time.time(),
                "owner_user_id": owner_user_id,
                "owner_username": owner_username,
            }

        def _bg():
            request_user_tokens = None
            if owner_user_id is not None:
                request_user_tokens = set_request_user(owner_user_id, owner_username)
            try:
                payload = _run_task()
                with _projects_lock:
                    _projects[task_id].update(payload)
            except Exception as exc:
                logger.error("Background task %s failed: %s", task_id, exc, exc_info=True)
                with _projects_lock:
                    _projects[task_id]["status"] = "failed"
                    _projects[task_id]["error"] = str(exc)
            finally:
                if request_user_tokens is not None:
                    reset_request_user(request_user_tokens)

        background_tasks.add_task(_bg)
        return APIResponse(
            data={"task_id": task_id, "status": "pending"},
            message="Task accepted. Poll /api/goals/{task_id} for updates.",
        )

    try:
        result = _run_task()
        return APIResponse(data=result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def start_server() -> None:
    """Canonical FastAPI startup entrypoint used by main.py."""
    import uvicorn

    reload_enabled = os.getenv("AETHER_RELOAD", "false").lower() == "true"
    workers = _env_int("AETHER_WORKERS", _env_int("AETHEER_WORKERS", 1, minimum=1), minimum=1)
    if reload_enabled and workers > 1:
        workers = 1

    uvicorn.run(
        "api.server:app",
        host=os.getenv("AETHER_HOST", "0.0.0.0"),
        port=int(os.getenv("AETHER_PORT", "8000")),
        reload=reload_enabled,
        workers=workers if not reload_enabled else None,
        limit_concurrency=_env_int("AETHER_LIMIT_CONCURRENCY", _runtime.config.max_concurrent_requests, minimum=1),
        backlog=_env_int("AETHER_BACKLOG", 2048, minimum=128),
        timeout_keep_alive=_env_int("AETHER_KEEPALIVE_SECONDS", 30, minimum=5),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    start_server()
