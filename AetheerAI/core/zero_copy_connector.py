"""
ZeroCopyConnector — Live data-source query hub (no stale copies).

Instead of ingesting data into a vector store, sub-agents query the
authoritative source *at execution time* — SQL databases, BigQuery,
Salesforce, REST APIs, CSV/Parquet files.

Architecture
------------
ZeroCopyRegistry   — registers / unregisters named connectors
ZeroCopyConnector  — per-source driver (SQL, BigQuery, Salesforce, REST, File)
KernelZeroCopy     — facade wired into AetheerAiKernel

Each connector exposes a single `query(statement, params)` method that
returns a list[dict] — always fresh from the live source.

Optional dependencies (install only what you need):
    pip install sqlalchemy                  # SQL databases
    pip install google-cloud-bigquery       # Google BigQuery
    pip install simple-salesforce           # Salesforce
    pip install pyarrow fastparquet         # Parquet/CSV files
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# ── Optional heavy imports — lazy-loaded per connector type ──────────────


def _sqlalchemy():
    try:
        import sqlalchemy as sa
        return sa
    except ImportError as exc:
        raise ImportError(
            "SQLAlchemy is required for SQL connectors.\n"
            "Install: pip install sqlalchemy"
        ) from exc


def _bigquery():
    try:
        from google.cloud import bigquery
        return bigquery
    except ImportError as exc:
        raise ImportError(
            "google-cloud-bigquery is required for BigQuery connectors.\n"
            "Install: pip install google-cloud-bigquery"
        ) from exc


def _simple_salesforce():
    try:
        import simple_salesforce as sf
        return sf
    except ImportError as exc:
        raise ImportError(
            "simple_salesforce is required for Salesforce connectors.\n"
            "Install: pip install simple-salesforce"
        ) from exc


# ═══════════════════════════════════════════════════════════════════════════
# Connector base
# ═══════════════════════════════════════════════════════════════════════════


class BaseConnector:
    """Abstract live connector.  Subclass and implement `query`."""

    kind: str = "base"

    def query(self, statement: str, params: dict | None = None) -> list[dict]:
        raise NotImplementedError

    def test(self) -> dict:
        """Run a lightweight connectivity check. Returns {"ok": bool, "message": str}."""
        try:
            self.query("SELECT 1", {})
            return {"ok": True, "message": "Connection successful"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def to_dict(self) -> dict:
        return {"kind": self.kind}


# ═══════════════════════════════════════════════════════════════════════════
# SQL connector (PostgreSQL, MySQL, SQLite, MSSQL — anything SQLAlchemy speaks)
# ═══════════════════════════════════════════════════════════════════════════


class SQLConnector(BaseConnector):
    """
    Live query against any SQLAlchemy-compatible database.

    Parameters
    ----------
    connection_string : SQLAlchemy URL, e.g.
        "postgresql://user:pass@host/dbname"
        "mysql+mysqlconnector://user:pass@host/dbname"
        "sqlite:///path/to/file.db"
    max_rows          : Hard cap on returned rows (safety guard, default 5000).
    """

    kind = "sql"

    def __init__(self, connection_string: str, max_rows: int = 5_000):
        sa = _sqlalchemy()
        self._engine = sa.create_engine(connection_string, pool_pre_ping=True)
        self.max_rows = max_rows
        self._connection_string = connection_string  # stored for to_dict (masked)

    def query(self, statement: str, params: dict | None = None) -> list[dict]:
        sa = _sqlalchemy()
        sanitized = statement.strip()
        with self._engine.connect() as conn:
            result = conn.execute(
                sa.text(sanitized),
                params or {},
            )
            rows = result.mappings().fetchmany(self.max_rows)
            return [dict(r) for r in rows]

    def test(self) -> dict:
        try:
            sa = _sqlalchemy()
            with self._engine.connect() as conn:
                conn.execute(sa.text("SELECT 1"))
            return {"ok": True, "message": "SQL connection successful"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def to_dict(self) -> dict:
        # Mask credentials in the stored URL
        try:
            sa = _sqlalchemy()
            url = sa.engine.make_url(self._connection_string)
            masked = url.render_as_string(hide_password=True)
        except Exception:
            masked = "***"
        return {"kind": self.kind, "connection_string": masked, "max_rows": self.max_rows}


# ═══════════════════════════════════════════════════════════════════════════
# Google BigQuery connector
# ═══════════════════════════════════════════════════════════════════════════


class BigQueryConnector(BaseConnector):
    """
    Live query against Google BigQuery.

    Parameters
    ----------
    project          : GCP project ID.
    credentials_path : Path to service-account JSON file.
                       Falls back to Application Default Credentials if None.
    max_rows         : Hard cap (default 5000).
    """

    kind = "bigquery"

    def __init__(
        self,
        project: str,
        credentials_path: str | None = None,
        max_rows: int = 5_000,
    ):
        bq = _bigquery()
        if credentials_path:
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file(credentials_path)
            self._client = bq.Client(project=project, credentials=creds)
        else:
            self._client = bq.Client(project=project)
        self.project = project
        self.max_rows = max_rows

    def query(self, statement: str, params: dict | None = None) -> list[dict]:
        job = self._client.query(statement)
        rows = job.result(max_results=self.max_rows)
        return [dict(row) for row in rows]

    def test(self) -> dict:
        try:
            job = self._client.query("SELECT 1")
            job.result()
            return {"ok": True, "message": "BigQuery connection successful"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def to_dict(self) -> dict:
        return {"kind": self.kind, "project": self.project, "max_rows": self.max_rows}


# ═══════════════════════════════════════════════════════════════════════════
# Salesforce connector
# ═══════════════════════════════════════════════════════════════════════════


class SalesforceConnector(BaseConnector):
    """
    Live SOQL query against Salesforce.

    Parameters
    ----------
    username, password, security_token : Salesforce auth credentials.
    domain : "login" (production) or "test" (sandbox).
    """

    kind = "salesforce"

    def __init__(
        self,
        username: str,
        password: str,
        security_token: str,
        domain: str = "login",
    ):
        sf_mod = _simple_salesforce()
        self._sf = sf_mod.Salesforce(
            username=username,
            password=password,
            security_token=security_token,
            domain=domain,
        )
        self.username = username
        self.domain = domain

    def query(self, statement: str, params: dict | None = None) -> list[dict]:
        result = self._sf.query_all(statement)
        records = result.get("records", [])
        # Strip Salesforce metadata keys
        cleaned = [
            {k: v for k, v in rec.items() if not k.startswith("attributes")}
            for rec in records
        ]
        return cleaned

    def test(self) -> dict:
        try:
            self._sf.query("SELECT Id FROM User LIMIT 1")
            return {"ok": True, "message": "Salesforce connection successful"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def to_dict(self) -> dict:
        return {"kind": self.kind, "username": self.username, "domain": self.domain}


# ═══════════════════════════════════════════════════════════════════════════
# REST API connector
# ═══════════════════════════════════════════════════════════════════════════


class RESTConnector(BaseConnector):
    """
    Live query against a REST JSON endpoint.

    Parameters
    ----------
    base_url     : Base URL of the API.
    headers      : Default HTTP headers (auth tokens, Accept, etc.).
    response_key : Dot-path into the JSON response containing the records list
                   (e.g. "data.items").  None means the root is the list.
    """

    kind = "rest"

    def __init__(
        self,
        base_url: str,
        headers: dict | None = None,
        response_key: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self.response_key = response_key

    def query(self, statement: str, params: dict | None = None) -> list[dict]:
        """
        ``statement`` is a path suffix (e.g.  "/users") or an absolute URL.
        ``params``    are appended as query-string parameters.
        """
        if statement.startswith("http"):
            url = statement
        else:
            url = self.base_url + statement

        if params:
            url = url + "?" + urllib.parse.urlencode(params)

        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read().decode())

        # Navigate response_key dot-path
        if self.response_key:
            for key in self.response_key.split("."):
                raw = raw[key]

        if isinstance(raw, list):
            return [r if isinstance(r, dict) else {"value": r} for r in raw]
        if isinstance(raw, dict):
            return [raw]
        return [{"value": raw}]

    def test(self) -> dict:
        try:
            req = urllib.request.Request(self.base_url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=10):
                pass
            return {"ok": True, "message": "REST endpoint reachable"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def to_dict(self) -> dict:
        return {"kind": self.kind, "base_url": self.base_url, "response_key": self.response_key}


# ═══════════════════════════════════════════════════════════════════════════
# File connector (CSV / JSON / JSONL / Parquet)
# ═══════════════════════════════════════════════════════════════════════════


class FileConnector(BaseConnector):
    """
    Read a local or mounted file as a live data source.

    Supported formats: .csv, .json, .jsonl, .parquet
    Note: files are re-read on every query — no caching.
    """

    kind = "file"

    def __init__(self, file_path: str, encoding: str = "utf-8"):
        self.file_path = file_path
        self.encoding = encoding

    def query(self, statement: str = "*", params: dict | None = None) -> list[dict]:
        path = self.file_path.lower()
        if path.endswith(".csv"):
            return self._read_csv()
        if path.endswith(".json"):
            return self._read_json()
        if path.endswith(".jsonl"):
            return self._read_jsonl()
        if path.endswith(".parquet"):
            return self._read_parquet()
        raise ValueError(f"Unsupported file format for zero-copy connector: {self.file_path}")

    def _read_csv(self) -> list[dict]:
        with open(self.file_path, newline="", encoding=self.encoding) as f:
            return list(csv.DictReader(f))

    def _read_json(self) -> list[dict]:
        with open(self.file_path, encoding=self.encoding) as f:
            data = json.load(f)
        return data if isinstance(data, list) else [data]

    def _read_jsonl(self) -> list[dict]:
        rows = []
        with open(self.file_path, encoding=self.encoding) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

    def _read_parquet(self) -> list[dict]:
        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError("pandas is required to read Parquet files.\nInstall: pip install pandas pyarrow") from exc
        df = pd.read_parquet(self.file_path)
        return df.to_dict(orient="records")

    def test(self) -> dict:
        if os.path.exists(self.file_path):
            return {"ok": True, "message": f"File exists: {self.file_path}"}
        return {"ok": False, "message": f"File not found: {self.file_path}"}

    def to_dict(self) -> dict:
        return {"kind": self.kind, "file_path": self.file_path}


# ═══════════════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════════════

_CONNECTOR_KINDS = {
    "sql": SQLConnector,
    "bigquery": BigQueryConnector,
    "salesforce": SalesforceConnector,
    "rest": RESTConnector,
    "file": FileConnector,
}


class ZeroCopyRegistry:
    """
    Thread-safe registry of named live-data connectors.

    Usage
    -----
    registry = ZeroCopyRegistry()
    registry.register("sales_db", SQLConnector("postgresql://..."))
    rows = registry.query("sales_db", "SELECT * FROM orders WHERE status='open'")
    """

    def __init__(self):
        self._connectors: dict[str, BaseConnector] = {}
        self._lock = threading.Lock()

    # ── Registration ─────────────────────────────────────────────────

    def register(self, name: str, connector: BaseConnector) -> None:
        with self._lock:
            self._connectors[name] = connector
        logger.info("ZeroCopy: registered connector '%s' (kind=%s)", name, connector.kind)

    def unregister(self, name: str) -> bool:
        with self._lock:
            if name in self._connectors:
                del self._connectors[name]
                logger.info("ZeroCopy: unregistered connector '%s'", name)
                return True
        return False

    def list_connectors(self) -> list[dict]:
        with self._lock:
            return [
                {"name": name, **conn.to_dict()}
                for name, conn in self._connectors.items()
            ]

    # ── Query ─────────────────────────────────────────────────────────

    def query(
        self,
        connector_name: str,
        statement: str,
        params: dict | None = None,
    ) -> list[dict]:
        """Execute a live query against the named connector."""
        with self._lock:
            conn = self._connectors.get(connector_name)
        if conn is None:
            raise KeyError(
                f"No zero-copy connector named '{connector_name}'. "
                f"Available: {list(self._connectors)}"
            )
        logger.info("ZeroCopy query [%s]: %.120s", connector_name, statement)
        rows = conn.query(statement, params)
        logger.info("ZeroCopy [%s]: returned %d rows", connector_name, len(rows))
        return rows

    # ── Test ──────────────────────────────────────────────────────────

    def test_connector(self, connector_name: str) -> dict:
        with self._lock:
            conn = self._connectors.get(connector_name)
        if conn is None:
            return {"ok": False, "message": f"Connector '{connector_name}' not found"}
        return conn.test()

    def test_all(self) -> dict[str, dict]:
        with self._lock:
            names = list(self._connectors)
        return {name: self.test_connector(name) for name in names}

    # ── Factory helper ────────────────────────────────────────────────

    @staticmethod
    def build_connector(kind: str, **kwargs) -> BaseConnector:
        """
        Build a connector from a kind string + kwargs.

        Example::
            conn = ZeroCopyRegistry.build_connector(
                "sql", connection_string="sqlite:///data.db"
            )
        """
        cls = _CONNECTOR_KINDS.get(kind)
        if cls is None:
            raise ValueError(
                f"Unknown connector kind '{kind}'. "
                f"Supported: {list(_CONNECTOR_KINDS)}"
            )
        return cls(**kwargs)
