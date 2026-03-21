"""Customer Supabase setup and per-customer data sync helpers.

This module stores each user's customer Supabase credentials inside the
platform Supabase project ("AetheerAI Supabase"), then uses those credentials
for customer-scoped operations such as:

- AI API settings persistence
- Memory key/value persistence for user-scoped memory DB operations
- Analytics-only account logs and AI token counters
- Agent profile metadata persistence
- Mirroring local DB write events to customer Supabase

Security design:
- Customer Supabase credentials and customer AI API keys are encrypted at rest.
- Platform analytics helpers intentionally store metadata-only logs (no raw prompts/results).
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import logging
import os
import re
import threading
import time
from collections.abc import Mapping
from typing import Any

from integrations.config.supabase_config import SupabaseConfig
from integrations.supabase_client import SupabaseClient

logger = logging.getLogger("aetheer.api.customer_supabase")

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_DEFAULT_CENTRAL_CONFIG_TABLE = "aetheer_customer_supabase_configs"
_DEFAULT_CENTRAL_ANALYTICS_LOG_TABLE = "aetheer_user_account_logs"
_DEFAULT_CENTRAL_TOKEN_COUNTER_TABLE = "aetheer_user_token_usage"
_DEFAULT_CENTRAL_AGENT_TABLE = "aetheer_user_agent_profiles"

_DEFAULT_CUSTOMER_AI_TABLE = "aetheer_ai_api_settings"
_DEFAULT_CUSTOMER_MIRROR_TABLE = "aetheer_db_entries"
_DEFAULT_CUSTOMER_LOG_TABLE = "aetheer_ai_logs"
_DEFAULT_CUSTOMER_TOKEN_COUNTER_TABLE = "aetheer_ai_token_counters"
_DEFAULT_CUSTOMER_MEMORY_TABLE = "aetheer_memory_store"

_ENCRYPTED_PREFIX = "enc:v1:"

_LOG_BLOCKED_FIELDS = {
    "prompt",
    "full_prompt",
    "input_text",
    "response",
    "result",
    "output",
    "payload",
    "message",
    "content",
    "raw",
    "body",
    "text",
    "error_traceback",
}
_LOG_MAX_VALUE_CHARS = 320
_LOG_MAX_LIST_ITEMS = 24

_config_cache_lock = threading.Lock()
_config_cache: dict[int, tuple[dict[str, Any] | None, float]] = {}
_setup_cache: dict[int, tuple[bool, float]] = {}

_cipher_lock = threading.Lock()
_secret_cipher: Any | None = None


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        value = int(raw) if raw else int(default)
    except ValueError:
        value = int(default)
    return max(minimum, value)


def _cache_ttl_seconds() -> int:
    return _env_int("AETHEER_CUSTOMER_SUPABASE_CACHE_SECONDS", 30, minimum=1)


def _safe_identifier(value: str, fallback: str) -> str:
    candidate = str(value or "").strip()
    if _IDENTIFIER_RE.fullmatch(candidate):
        return candidate
    return fallback


def _central_config_table() -> str:
    return _safe_identifier(
        os.getenv("AETHEER_CUSTOMER_CONFIG_TABLE", _DEFAULT_CENTRAL_CONFIG_TABLE),
        _DEFAULT_CENTRAL_CONFIG_TABLE,
    )


def _central_analytics_log_table() -> str:
    return _safe_identifier(
        os.getenv("AETHEER_CENTRAL_ANALYTICS_LOG_TABLE", _DEFAULT_CENTRAL_ANALYTICS_LOG_TABLE),
        _DEFAULT_CENTRAL_ANALYTICS_LOG_TABLE,
    )


def _central_token_counter_table() -> str:
    return _safe_identifier(
        os.getenv("AETHEER_CENTRAL_TOKEN_COUNTER_TABLE", _DEFAULT_CENTRAL_TOKEN_COUNTER_TABLE),
        _DEFAULT_CENTRAL_TOKEN_COUNTER_TABLE,
    )


def _central_agent_table() -> str:
    return _safe_identifier(
        os.getenv("AETHEER_CENTRAL_AGENT_TABLE", _DEFAULT_CENTRAL_AGENT_TABLE),
        _DEFAULT_CENTRAL_AGENT_TABLE,
    )


def _customer_ai_table() -> str:
    return _safe_identifier(
        os.getenv("AETHEER_CUSTOMER_AI_TABLE", _DEFAULT_CUSTOMER_AI_TABLE),
        _DEFAULT_CUSTOMER_AI_TABLE,
    )


def _customer_mirror_table() -> str:
    return _safe_identifier(
        os.getenv("AETHEER_CUSTOMER_MIRROR_TABLE", _DEFAULT_CUSTOMER_MIRROR_TABLE),
        _DEFAULT_CUSTOMER_MIRROR_TABLE,
    )


def _customer_log_table() -> str:
    return _safe_identifier(
        os.getenv("AETHEER_CUSTOMER_LOG_TABLE", _DEFAULT_CUSTOMER_LOG_TABLE),
        _DEFAULT_CUSTOMER_LOG_TABLE,
    )


def _customer_token_counter_table() -> str:
    return _safe_identifier(
        os.getenv("AETHEER_CUSTOMER_TOKEN_COUNTER_TABLE", _DEFAULT_CUSTOMER_TOKEN_COUNTER_TABLE),
        _DEFAULT_CUSTOMER_TOKEN_COUNTER_TABLE,
    )


def _customer_memory_table() -> str:
    return _safe_identifier(
        os.getenv("AETHEER_CUSTOMER_MEMORY_TABLE", _DEFAULT_CUSTOMER_MEMORY_TABLE),
        _DEFAULT_CUSTOMER_MEMORY_TABLE,
    )


def _customer_schema_default() -> str:
    schema = (os.getenv("AETHEER_CUSTOMER_SUPABASE_SCHEMA") or "public").strip().lower()
    return _safe_identifier(schema, "public")


def _normalize_url(url: str) -> str:
    return str(url or "").strip().rstrip("/")


def _truncate_text(value: Any, *, max_chars: int = _LOG_MAX_VALUE_CHARS) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _redact_secret(value: Any, *, prefix: int = 4, suffix: int = 2) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= (prefix + suffix + 3):
        return "***"
    return f"{text[:prefix]}***{text[-suffix:]}"


def _rows_from_response(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        nested = payload.get("data")
        if isinstance(nested, list):
            return [row for row in nested if isinstance(row, dict)]
        if payload:
            return [payload]
    return []


def _build_platform_supabase_client() -> SupabaseClient:
    return SupabaseClient()


def _customer_supabase_timeout_seconds() -> int:
    return _env_int("AETHEER_CUSTOMER_SUPABASE_TIMEOUT_SECONDS", 20, minimum=1)


def _cache_set(user_id: int, config_row: dict[str, Any] | None) -> None:
    now = time.time()
    ttl = _cache_ttl_seconds()
    configured = _row_is_configured(config_row)
    with _config_cache_lock:
        _config_cache[int(user_id)] = (config_row, now + ttl)
        _setup_cache[int(user_id)] = (configured, now + ttl)


def _cache_get_config(user_id: int) -> dict[str, Any] | None | None:
    now = time.time()
    with _config_cache_lock:
        item = _config_cache.get(int(user_id))
        if not item:
            return None
        value, expires_at = item
        if expires_at < now:
            _config_cache.pop(int(user_id), None)
            return None
        return value


def _cache_get_setup(user_id: int) -> bool | None:
    now = time.time()
    with _config_cache_lock:
        item = _setup_cache.get(int(user_id))
        if not item:
            return None
        value, expires_at = item
        if expires_at < now:
            _setup_cache.pop(int(user_id), None)
            return None
        return bool(value)


def _invalidate_cache(user_id: int) -> None:
    with _config_cache_lock:
        _config_cache.pop(int(user_id), None)
        _setup_cache.pop(int(user_id), None)


def _encryption_material() -> str:
    # Prefer dedicated encryption keys, then fall back to service-role secrets.
    candidates = (
        "AETHEER_SUPABASE_CONFIG_ENCRYPTION_KEY",
        "AETHEER_SUPABASE_CONFIG_ENCRYPTION_SECRET",
        "AETHEER_PLATFORM_ENCRYPTION_KEY",
        "AETHEER_SECRET_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
    )
    for env_name in candidates:
        value = (os.getenv(env_name) or "").strip()
        if value:
            return value
    return ""


def _derive_fernet_key(material: str) -> bytes:
    text = str(material or "").strip()
    if not text:
        return b""

    try:
        padded = text + "=" * (-len(text) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("utf-8"))
        if len(raw) == 32:
            return base64.urlsafe_b64encode(raw)
    except Exception:
        pass

    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _get_secret_cipher(*, required: bool) -> Any | None:
    global _secret_cipher

    with _cipher_lock:
        if _secret_cipher is not None:
            return _secret_cipher

        material = _encryption_material()
        if not material:
            if required:
                raise RuntimeError(
                    "Missing encryption key material. Set "
                    "AETHEER_SUPABASE_CONFIG_ENCRYPTION_KEY (or equivalent)."
                )
            return None

        try:
            from cryptography.fernet import Fernet  # type: ignore
        except ImportError as exc:
            if required:
                raise RuntimeError(
                    "cryptography is required for encrypted credential storage."
                ) from exc
            return None

        key = _derive_fernet_key(material)
        if not key:
            if required:
                raise RuntimeError("Unable to derive encryption key for credential encryption.")
            return None

        _secret_cipher = Fernet(key)
        return _secret_cipher


def _is_encrypted_secret(value: str) -> bool:
    return str(value or "").startswith(_ENCRYPTED_PREFIX)


def _encrypt_secret(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if _is_encrypted_secret(text):
        return text

    cipher = _get_secret_cipher(required=True)
    assert cipher is not None
    token = cipher.encrypt(text.encode("utf-8")).decode("utf-8")
    return f"{_ENCRYPTED_PREFIX}{token}"


def _decrypt_secret(value: Any, *, strict: bool) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not _is_encrypted_secret(text):
        return text

    cipher = _get_secret_cipher(required=strict)
    if cipher is None:
        return ""

    token = text[len(_ENCRYPTED_PREFIX):]
    try:
        return cipher.decrypt(token.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        if strict:
            raise RuntimeError("Unable to decrypt encrypted Supabase credential.") from exc
        logger.warning("Encrypted credential could not be decrypted: %s", exc)
        return ""


def _resolve_secret_for_read(value: Any, *, strict: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if _is_encrypted_secret(text):
        return _decrypt_secret(text, strict=strict)
    return text


def _row_is_configured(row: Mapping[str, Any] | None) -> bool:
    if not isinstance(row, Mapping):
        return False
    url = _normalize_url(str(row.get("customer_supabase_url") or ""))
    anon_key = _resolve_secret_for_read(row.get("customer_supabase_anon_key"), strict=False)
    return bool(url and anon_key)


def _normalize_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            out[str(k)] = _normalize_json_value(v)
        return out
    if isinstance(value, (list, tuple, set)):
        return [_normalize_json_value(v) for v in value]
    return str(value)


def _sanitize_metadata_value(value: Any, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate_text(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()

    if depth >= 2:
        return _truncate_text(value)

    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for raw_key, raw_val in value.items():
            key = str(raw_key or "").strip().lower()
            if not key or key in _LOG_BLOCKED_FIELDS:
                continue
            output[key] = _sanitize_metadata_value(raw_val, depth=depth + 1)
        return output

    if isinstance(value, (list, tuple, set)):
        trimmed = list(value)[:_LOG_MAX_LIST_ITEMS]
        return [_sanitize_metadata_value(item, depth=depth + 1) for item in trimmed]

    return _truncate_text(value)


def _sanitize_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, Mapping):
        return {}

    output: dict[str, Any] = {}
    for raw_key, raw_val in metadata.items():
        key = str(raw_key or "").strip().lower()
        if not key or key in _LOG_BLOCKED_FIELDS:
            continue
        output[key] = _sanitize_metadata_value(raw_val)
    return output


def _clean_text_list(values: Any, *, max_items: int = 32, max_chars: int = 160) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    cleaned: list[str] = []
    for item in list(values)[:max_items]:
        text = str(item or "").strip()
        if not text:
            continue
        cleaned.append(text[:max_chars])
    return cleaned


def _eq_filter(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"eq.{value}"
    text = str(value or "")
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'eq."{escaped}"'


def get_customer_supabase_setup_sql() -> str:
    """SQL to run in each customer's Supabase project."""
    schema = _customer_schema_default()
    ai_table = _customer_ai_table()
    mirror_table = _customer_mirror_table()
    log_table = _customer_log_table()
    token_table = _customer_token_counter_table()
    memory_table = _customer_memory_table()

    return f"""-- AetheerAI customer bootstrap SQL
-- Run this script in the CUSTOMER's Supabase SQL editor.

create schema if not exists {schema};

create table if not exists {schema}.{ai_table} (
  id bigserial primary key,
  user_id bigint not null,
  username text,
  provider text not null,
  model text,
  api_key text,
  base_url text,
  extra jsonb not null default '{{}}'::jsonb,
  updated_at timestamptz not null default timezone('utc', now()),
  unique (user_id)
);

create table if not exists {schema}.{mirror_table} (
  id bigserial primary key,
  user_id bigint not null,
  source_table text not null,
  operation text not null,
  source_row_id text,
  payload jsonb not null,
  mirrored_at timestamptz not null default timezone('utc', now())
);

create table if not exists {schema}.{log_table} (
  id bigserial primary key,
  user_id bigint not null,
  event_type text not null,
  action text not null,
  status text not null default 'ok',
  provider text,
  model text,
  metadata jsonb not null default '{{}}'::jsonb,
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists {schema}.{token_table} (
  id bigserial primary key,
  user_id bigint not null,
  provider text not null,
  model text not null default '',
  prompt_tokens bigint not null default 0,
  completion_tokens bigint not null default 0,
  total_tokens bigint not null default 0,
  updated_at timestamptz not null default timezone('utc', now()),
  unique (user_id, provider, model)
);

create table if not exists {schema}.{memory_table} (
  id bigserial primary key,
  user_id bigint not null,
  namespace text not null default 'global',
  memory_key text not null,
  memory_value jsonb not null default '{{}}'::jsonb,
  updated_at timestamptz not null default timezone('utc', now()),
  unique (user_id, namespace, memory_key)
);

create index if not exists idx_{mirror_table}_user_id on {schema}.{mirror_table}(user_id);
create index if not exists idx_{mirror_table}_source_table on {schema}.{mirror_table}(source_table);
create index if not exists idx_{mirror_table}_mirrored_at on {schema}.{mirror_table}(mirrored_at desc);

create index if not exists idx_{log_table}_user_id on {schema}.{log_table}(user_id);
create index if not exists idx_{log_table}_event_type on {schema}.{log_table}(event_type);
create index if not exists idx_{log_table}_created_at on {schema}.{log_table}(created_at desc);

create index if not exists idx_{token_table}_user_id on {schema}.{token_table}(user_id);
create index if not exists idx_{token_table}_provider on {schema}.{token_table}(provider);

create index if not exists idx_{memory_table}_user_ns on {schema}.{memory_table}(user_id, namespace);
create index if not exists idx_{memory_table}_updated_at on {schema}.{memory_table}(updated_at desc);
"""


def get_platform_supabase_setup_sql() -> str:
    """SQL to run in the platform (AetheerAI) Supabase project."""
    config_table = _central_config_table()
    analytics_table = _central_analytics_log_table()
    token_table = _central_token_counter_table()
    agent_table = _central_agent_table()

    return f"""-- AetheerAI platform bootstrap SQL
-- Run this script in the AETHEERAI Supabase SQL editor.

create table if not exists public.{config_table} (
  id bigserial primary key,
  user_id bigint not null unique,
  username text,
  customer_supabase_url text not null,
  customer_supabase_anon_key text not null,
  customer_supabase_service_role_key text,
  customer_supabase_schema text not null default 'public',
  setup_completed boolean not null default true,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.{analytics_table} (
  id bigserial primary key,
  user_id bigint not null,
  username text,
  event_type text not null,
  action text not null,
  status text not null default 'ok',
  provider text,
  model text,
  metadata jsonb not null default '{{}}'::jsonb,
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.{token_table} (
  id bigserial primary key,
  user_id bigint not null,
  username text,
  provider text not null,
  model text not null default '',
  prompt_tokens bigint not null default 0,
  completion_tokens bigint not null default 0,
  total_tokens bigint not null default 0,
  last_event_at timestamptz not null default timezone('utc', now()),
  unique (user_id, provider, model)
);

create table if not exists public.{agent_table} (
  id bigserial primary key,
  user_id bigint not null,
  username text,
  agent_name text not null,
  role text,
  source text not null default 'manual',
  tools jsonb not null default '[]'::jsonb,
  skills jsonb not null default '[]'::jsonb,
  objectives jsonb not null default '[]'::jsonb,
  permission_level integer,
  metadata jsonb not null default '{{}}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  unique (user_id, agent_name)
);

create index if not exists idx_{config_table}_user_id on public.{config_table}(user_id);

create index if not exists idx_{analytics_table}_user_id on public.{analytics_table}(user_id);
create index if not exists idx_{analytics_table}_event_type on public.{analytics_table}(event_type);
create index if not exists idx_{analytics_table}_created_at on public.{analytics_table}(created_at desc);

create index if not exists idx_{token_table}_user_id on public.{token_table}(user_id);
create index if not exists idx_{token_table}_provider on public.{token_table}(provider);

create index if not exists idx_{agent_table}_user_id on public.{agent_table}(user_id);
create index if not exists idx_{agent_table}_agent_name on public.{agent_table}(agent_name);
"""


def save_customer_supabase_config(
    *,
    user_id: int,
    username: str,
    supabase_url: str,
    supabase_anon_key: str,
    supabase_service_role_key: str | None,
    schema: str | None,
) -> dict[str, Any]:
    """Persist customer Supabase credentials in the platform Supabase."""
    uid = int(user_id)
    anon_key_raw = str(supabase_anon_key or "").strip()
    if not anon_key_raw:
        raise ValueError("supabase_anon_key is required")

    service_role_key_raw = str(supabase_service_role_key or "").strip() or None

    now = _utc_now_iso()
    payload = {
        "user_id": uid,
        "username": str(username or "").strip() or None,
        "customer_supabase_url": _normalize_url(supabase_url),
        # Encrypted at rest in platform Supabase.
        "customer_supabase_anon_key": _encrypt_secret(anon_key_raw),
        "customer_supabase_service_role_key": (
            _encrypt_secret(service_role_key_raw) if service_role_key_raw else None
        ),
        "customer_supabase_schema": _safe_identifier(str(schema or "").strip().lower(), _customer_schema_default()),
        "setup_completed": True,
        "updated_at": now,
        "created_at": now,
    }

    client = _build_platform_supabase_client()
    response = client.insert_row(
        table=_central_config_table(),
        payload=payload,
        use_service_role=True,
        upsert=True,
    )

    rows = _rows_from_response(response)
    row = rows[0] if rows else payload
    _cache_set(uid, row)
    return row


def get_customer_supabase_config(
    user_id: int,
    *,
    use_cache: bool = True,
) -> dict[str, Any] | None:
    """Load customer Supabase credentials for a user."""
    uid = int(user_id)

    if use_cache:
        cached = _cache_get_config(uid)
        if cached is not None:
            return cached

    try:
        client = _build_platform_supabase_client()
        response = client.query_rows(
            table=_central_config_table(),
            filters={"user_id": f"eq.{uid}"},
            limit=1,
            use_service_role=True,
        )
        rows = _rows_from_response(response)
        row = rows[0] if rows else None
        _cache_set(uid, row)
        return row
    except Exception as exc:
        logger.warning("Failed to query platform Supabase customer config for user=%s: %s", uid, exc)
        _cache_set(uid, None)
        return None


def get_customer_setup_status(user_id: int, *, use_cache: bool = True) -> dict[str, Any]:
    """Return setup readiness for a user (first-login gate)."""
    uid = int(user_id)

    configured: bool
    if use_cache:
        cached = _cache_get_setup(uid)
        if cached is not None:
            configured = bool(cached)
            row = _cache_get_config(uid)
            return {
                "configured": configured,
                "requires_setup": not configured,
                "customer_supabase_url": _normalize_url(str((row or {}).get("customer_supabase_url") or "")),
                "customer_supabase_schema": str((row or {}).get("customer_supabase_schema") or _customer_schema_default()),
            }

    row = get_customer_supabase_config(uid, use_cache=use_cache)
    configured = _row_is_configured(row)
    return {
        "configured": configured,
        "requires_setup": not configured,
        "customer_supabase_url": _normalize_url(str((row or {}).get("customer_supabase_url") or "")),
        "customer_supabase_schema": str((row or {}).get("customer_supabase_schema") or _customer_schema_default()),
    }


def is_customer_supabase_configured(user_id: int, *, use_cache: bool = True) -> bool:
    uid = int(user_id)
    if use_cache:
        cached = _cache_get_setup(uid)
        if cached is not None:
            return bool(cached)

    try:
        row = get_customer_supabase_config(uid, use_cache=use_cache)
        configured = _row_is_configured(row)
        _cache_set(uid, row)
        return configured
    except Exception:
        return False


def redact_customer_supabase_config(row: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        return {
            "configured": False,
            "customer_supabase_url": "",
            "customer_supabase_schema": _customer_schema_default(),
            "customer_supabase_anon_key": "",
            "customer_supabase_service_role_key": "",
        }

    anon_key = _resolve_secret_for_read(row.get("customer_supabase_anon_key"), strict=False)
    service_role_key = _resolve_secret_for_read(row.get("customer_supabase_service_role_key"), strict=False)
    return {
        "configured": _row_is_configured(row),
        "customer_supabase_url": _normalize_url(str(row.get("customer_supabase_url") or "")),
        "customer_supabase_schema": str(row.get("customer_supabase_schema") or _customer_schema_default()),
        "customer_supabase_anon_key": _redact_secret(anon_key),
        "customer_supabase_service_role_key": _redact_secret(service_role_key),
    }


def _build_customer_client_from_row(row: Mapping[str, Any]) -> SupabaseClient:
    url = _normalize_url(str(row.get("customer_supabase_url") or ""))
    anon_key = _resolve_secret_for_read(row.get("customer_supabase_anon_key"), strict=True)
    service_role_key = _resolve_secret_for_read(row.get("customer_supabase_service_role_key"), strict=True)
    schema = _safe_identifier(str(row.get("customer_supabase_schema") or "").strip().lower(), _customer_schema_default())

    cfg = SupabaseConfig(
        url=url,
        anon_key=anon_key,
        service_role_key=service_role_key,
        schema=schema,
        timeout_seconds=_customer_supabase_timeout_seconds(),
    )
    return SupabaseClient(config=cfg)


def _customer_client_for_user(user_id: int) -> SupabaseClient:
    row = get_customer_supabase_config(user_id)
    if not _row_is_configured(row):
        raise RuntimeError("Customer Supabase is not configured for this user.")
    assert isinstance(row, Mapping)
    return _build_customer_client_from_row(row)


def save_customer_ai_api_settings(
    *,
    user_id: int,
    username: str,
    provider: str,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    extra: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Persist AI API settings to the customer Supabase project."""
    uid = int(user_id)
    client = _customer_client_for_user(uid)

    api_key_raw = str(api_key or "").strip() or None
    payload = {
        "user_id": uid,
        "username": str(username or "").strip() or None,
        "provider": str(provider or "").strip().lower(),
        "model": str(model or "").strip() or None,
        # Stored encrypted at rest in user Supabase.
        "api_key": _encrypt_secret(api_key_raw) if api_key_raw else None,
        "base_url": _normalize_url(str(base_url or "")) or None,
        "extra": _normalize_json_value(dict(extra or {})),
        "updated_at": _utc_now_iso(),
    }

    response = client.insert_row(
        table=_customer_ai_table(),
        payload=payload,
        use_service_role=True,
        upsert=True,
        on_conflict="user_id",
    )
    rows = _rows_from_response(response)
    return rows[0] if rows else payload


def get_customer_ai_api_settings(
    *,
    user_id: int,
    include_secret: bool = False,
) -> dict[str, Any] | None:
    uid = int(user_id)
    client = _customer_client_for_user(uid)
    response = client.query_rows(
        table=_customer_ai_table(),
        filters={"user_id": f"eq.{uid}"},
        limit=1,
        use_service_role=True,
    )
    rows = _rows_from_response(response)
    if not rows:
        return None

    row = dict(rows[0])
    api_key = _resolve_secret_for_read(row.get("api_key"), strict=False)
    row["api_key"] = api_key if include_secret else _redact_secret(api_key)
    return row


def save_customer_memory_entry(
    *,
    user_id: int,
    namespace: str,
    key: str,
    value: Any,
) -> dict[str, Any]:
    """Store a memory key/value in the user's Supabase memory table."""
    uid = int(user_id)
    memory_key = str(key or "").strip()
    if not memory_key:
        raise ValueError("memory key is required")

    payload = {
        "user_id": uid,
        "namespace": str(namespace or "global").strip() or "global",
        "memory_key": memory_key[:255],
        "memory_value": _normalize_json_value(value),
        "updated_at": _utc_now_iso(),
    }

    client = _customer_client_for_user(uid)
    response = client.insert_row(
        table=_customer_memory_table(),
        payload=payload,
        use_service_role=True,
        upsert=True,
    )
    rows = _rows_from_response(response)
    return rows[0] if rows else payload


def get_customer_memory_entry(
    *,
    user_id: int,
    namespace: str,
    key: str,
) -> dict[str, Any] | None:
    uid = int(user_id)
    memory_key = str(key or "").strip()
    if not memory_key:
        return None

    client = _customer_client_for_user(uid)
    response = client.query_rows(
        table=_customer_memory_table(),
        filters={
            "user_id": f"eq.{uid}",
            "namespace": _eq_filter(str(namespace or "global").strip() or "global"),
            "memory_key": _eq_filter(memory_key),
        },
        limit=1,
        use_service_role=True,
    )
    rows = _rows_from_response(response)
    return rows[0] if rows else None


def list_customer_memory_entries(
    *,
    user_id: int,
    namespace: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    uid = int(user_id)
    client = _customer_client_for_user(uid)
    response = client.query_rows(
        table=_customer_memory_table(),
        filters={
            "user_id": f"eq.{uid}",
            "namespace": _eq_filter(str(namespace or "global").strip() or "global"),
        },
        limit=max(1, min(2000, int(limit))),
        order="updated_at.desc",
        use_service_role=True,
    )
    return _rows_from_response(response)


def delete_customer_memory_entry(
    *,
    user_id: int,
    namespace: str,
    key: str,
) -> bool:
    uid = int(user_id)
    memory_key = str(key or "").strip()
    if not memory_key:
        return False

    client = _customer_client_for_user(uid)
    response = client.delete_rows(
        table=_customer_memory_table(),
        filters={
            "user_id": f"eq.{uid}",
            "namespace": _eq_filter(str(namespace or "global").strip() or "global"),
            "memory_key": _eq_filter(memory_key),
        },
        use_service_role=True,
    )
    return bool(_rows_from_response(response))


def mirror_db_entry_best_effort(
    *,
    user_id: int,
    source_table: str,
    operation: str,
    source_row_id: str | None,
    payload: Mapping[str, Any],
) -> bool:
    """Best-effort mirror of a local DB write into customer Supabase."""
    uid = int(user_id)
    if uid <= 0:
        return False

    if not is_customer_supabase_configured(uid):
        return False

    try:
        client = _customer_client_for_user(uid)
        client.insert_row(
            table=_customer_mirror_table(),
            payload={
                "user_id": uid,
                "source_table": str(source_table or "").strip()[:160],
                "operation": str(operation or "").strip().lower()[:32],
                "source_row_id": str(source_row_id or "").strip()[:128] or None,
                "payload": _normalize_json_value(dict(payload or {})),
                "mirrored_at": _utc_now_iso(),
            },
            use_service_role=True,
            upsert=False,
        )
        return True
    except Exception as exc:
        logger.warning(
            "Customer DB mirror failed (user_id=%s table=%s op=%s): %s",
            uid,
            source_table,
            operation,
            exc,
        )
        return False


def _insert_platform_row_best_effort(*, table: str, payload: Mapping[str, Any], upsert: bool = False) -> bool:
    try:
        client = _build_platform_supabase_client()
        client.insert_row(
            table=table,
            payload=_normalize_json_value(dict(payload or {})),
            use_service_role=True,
            upsert=upsert,
        )
        return True
    except Exception as exc:
        logger.warning("Platform Supabase write failed (table=%s): %s", table, exc)
        return False


def _insert_customer_row_best_effort(*, user_id: int, table: str, payload: Mapping[str, Any], upsert: bool = False) -> bool:
    uid = int(user_id)
    if uid <= 0:
        return False
    try:
        client = _customer_client_for_user(uid)
        client.insert_row(
            table=table,
            payload=_normalize_json_value(dict(payload or {})),
            use_service_role=True,
            upsert=upsert,
        )
        return True
    except Exception as exc:
        logger.warning("Customer Supabase write failed (user_id=%s table=%s): %s", uid, table, exc)
        return False


def record_user_analytics_log_best_effort(
    *,
    user_id: int,
    username: str | None,
    event_type: str,
    action: str,
    status: str = "ok",
    provider: str | None = None,
    model: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, bool]:
    """Write metadata-only analytics logs to platform + customer Supabase.

    This helper intentionally stores only sanitized metadata and never writes
    prompt/response payloads into platform analytics tables.
    """
    uid = int(user_id)
    if uid <= 0:
        return {"platform": False, "customer": False}

    payload = {
        "user_id": uid,
        "username": str(username or "").strip() or None,
        "event_type": str(event_type or "event").strip().lower()[:64] or "event",
        "action": str(action or "action").strip().lower()[:96] or "action",
        "status": str(status or "ok").strip().lower()[:24] or "ok",
        "provider": str(provider or "").strip().lower()[:64] or None,
        "model": str(model or "").strip()[:160] or None,
        "metadata": _sanitize_metadata(metadata),
        "created_at": _utc_now_iso(),
    }

    platform_ok = _insert_platform_row_best_effort(
        table=_central_analytics_log_table(),
        payload=payload,
        upsert=False,
    )

    customer_payload = {
        "user_id": uid,
        "event_type": payload["event_type"],
        "action": payload["action"],
        "status": payload["status"],
        "provider": payload["provider"],
        "model": payload["model"],
        "metadata": payload["metadata"],
        "created_at": payload["created_at"],
    }
    customer_ok = _insert_customer_row_best_effort(
        user_id=uid,
        table=_customer_log_table(),
        payload=customer_payload,
        upsert=False,
    )

    return {"platform": platform_ok, "customer": customer_ok}


def _increment_token_counter_best_effort(
    *,
    client: SupabaseClient,
    table: str,
    filters: Mapping[str, str],
    base_payload: Mapping[str, Any],
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    timestamp_field: str,
) -> bool:
    try:
        existing_response = client.query_rows(
            table=table,
            filters=filters,
            limit=1,
            use_service_role=True,
        )
        rows = _rows_from_response(existing_response)
        existing = rows[0] if rows else {}

        payload = dict(base_payload)
        payload["prompt_tokens"] = int(existing.get("prompt_tokens") or 0) + prompt_tokens
        payload["completion_tokens"] = int(existing.get("completion_tokens") or 0) + completion_tokens
        payload["total_tokens"] = int(existing.get("total_tokens") or 0) + total_tokens
        payload[timestamp_field] = _utc_now_iso()

        client.insert_row(
            table=table,
            payload=payload,
            use_service_role=True,
            upsert=True,
        )
        return True
    except Exception as exc:
        logger.warning("Token counter upsert failed (table=%s): %s", table, exc)
        return False


def record_user_token_usage_best_effort(
    *,
    user_id: int,
    username: str | None,
    provider: str,
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, bool]:
    """Increment token counters in platform + customer Supabase and emit analytics logs."""
    uid = int(user_id)
    if uid <= 0:
        return {
            "platform_counter": False,
            "customer_counter": False,
            "platform_log": False,
            "customer_log": False,
        }

    provider_norm = str(provider or "unknown").strip().lower()[:64] or "unknown"
    model_norm = str(model or "").strip()[:160]
    prompt_value = max(0, int(prompt_tokens or 0))
    completion_value = max(0, int(completion_tokens or 0))
    total_value = max(0, int(total_tokens or 0))
    if total_value <= 0:
        total_value = prompt_value + completion_value

    platform_counter_ok = False
    try:
        platform_client = _build_platform_supabase_client()
        platform_counter_ok = _increment_token_counter_best_effort(
            client=platform_client,
            table=_central_token_counter_table(),
            filters={
                "user_id": f"eq.{uid}",
                "provider": _eq_filter(provider_norm),
                "model": _eq_filter(model_norm),
            },
            base_payload={
                "user_id": uid,
                "username": str(username or "").strip() or None,
                "provider": provider_norm,
                "model": model_norm,
            },
            prompt_tokens=prompt_value,
            completion_tokens=completion_value,
            total_tokens=total_value,
            timestamp_field="last_event_at",
        )
    except Exception as exc:
        logger.warning("Platform token counter write failed (user_id=%s): %s", uid, exc)

    customer_counter_ok = False
    try:
        customer_client = _customer_client_for_user(uid)
        customer_counter_ok = _increment_token_counter_best_effort(
            client=customer_client,
            table=_customer_token_counter_table(),
            filters={
                "user_id": f"eq.{uid}",
                "provider": _eq_filter(provider_norm),
                "model": _eq_filter(model_norm),
            },
            base_payload={
                "user_id": uid,
                "provider": provider_norm,
                "model": model_norm,
            },
            prompt_tokens=prompt_value,
            completion_tokens=completion_value,
            total_tokens=total_value,
            timestamp_field="updated_at",
        )
    except Exception as exc:
        logger.warning("Customer token counter write failed (user_id=%s): %s", uid, exc)

    log_metadata = dict(_sanitize_metadata(metadata))
    log_metadata.update(
        {
            "prompt_tokens": prompt_value,
            "completion_tokens": completion_value,
            "total_tokens": total_value,
        }
    )
    log_result = record_user_analytics_log_best_effort(
        user_id=uid,
        username=username,
        event_type="ai_usage",
        action="token_counter_update",
        status="ok",
        provider=provider_norm,
        model=model_norm,
        metadata=log_metadata,
    )

    return {
        "platform_counter": platform_counter_ok,
        "customer_counter": customer_counter_ok,
        "platform_log": bool(log_result.get("platform")),
        "customer_log": bool(log_result.get("customer")),
    }


def record_user_agent_profile_best_effort(
    *,
    user_id: int,
    username: str | None,
    agent_name: str,
    role: str | None,
    source: str,
    tools: list[str] | tuple[str, ...] | None,
    skills: list[str] | tuple[str, ...] | None,
    objectives: list[str] | tuple[str, ...] | None,
    permission_level: int | None,
    metadata: Mapping[str, Any] | None = None,
) -> bool:
    """Persist user-created agent metadata in platform Supabase."""
    uid = int(user_id)
    if uid <= 0:
        return False

    agent_name_clean = str(agent_name or "").strip()
    if not agent_name_clean:
        return False

    payload = {
        "user_id": uid,
        "username": str(username or "").strip() or None,
        "agent_name": agent_name_clean[:160],
        "role": str(role or "").strip()[:160] or None,
        "source": str(source or "manual").strip().lower()[:32] or "manual",
        "tools": _clean_text_list(tools),
        "skills": _clean_text_list(skills),
        "objectives": _clean_text_list(objectives, max_items=48, max_chars=260),
        "permission_level": int(permission_level) if permission_level is not None else None,
        "metadata": _sanitize_metadata(metadata),
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
    }

    saved = _insert_platform_row_best_effort(
        table=_central_agent_table(),
        payload=payload,
        upsert=True,
    )

    record_user_analytics_log_best_effort(
        user_id=uid,
        username=username,
        event_type="agent",
        action="agent_profile_upsert",
        status="ok" if saved else "error",
        metadata={
            "agent_name": payload["agent_name"],
            "source": payload["source"],
            "tools_count": len(payload["tools"]),
            "skills_count": len(payload["skills"]),
            "objectives_count": len(payload["objectives"]),
        },
    )
    return saved


def clear_customer_supabase_cache(user_id: int | None = None) -> None:
    if user_id is None:
        with _config_cache_lock:
            _config_cache.clear()
            _setup_cache.clear()
        return
    _invalidate_cache(int(user_id))

