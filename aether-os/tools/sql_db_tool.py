"""
sql_db_tool — Execute SQL queries against relational databases.

Requires:  pip install sqlalchemy
           pip install psycopg2-binary    (PostgreSQL)
           pip install pymysql            (MySQL / MariaDB)

Env vars:
    DATABASE_URL — SQLAlchemy connection string, e.g.:
        sqlite:///mydb.db
        postgresql://user:pass@localhost:5432/dbname
        mysql+pymysql://user:pass@localhost/dbname

Actions
-------
  query   : Execute a SELECT statement and return formatted results.
  execute : Execute a DML statement (INSERT/UPDATE/DELETE). Requires confirm="yes".
  tables  : List all tables in the database.
  schema  : Show column names and types for a given table.
  explain : Show the query plan for a SELECT (dialect-dependent).

Security
--------
  • Only parameterised queries are supported for user-supplied values.
  • Raw DDL (DROP/TRUNCATE/ALTER) commands are blocked and require confirm="yes".
  • DATABASE_URL is read from the environment — never passed as an argument.
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

# DDL keywords that are always blocked unless explicitly confirmed
_BLOCKED_DDL = re.compile(
    r"^\s*(drop|truncate|alter|create\s+table|grant|revoke)\b",
    re.IGNORECASE,
)

# Max rows to return in query results to avoid context overflow
_MAX_ROWS = 100


def sql_db_tool(
    action: str,
    sql: str = "",
    table: str = "",
    confirm: str = "",
    params: str = "",
) -> str:
    """
    Run SQL operations against the configured database.

    action  : query | execute | tables | schema | explain
    sql     : SQL statement for query/execute/explain.
    table   : Table name for 'schema' action.
    confirm : Pass "yes" to allow DML (INSERT/UPDATE/DELETE) or blocked DDL.
    params  : JSON object of bind parameters, e.g. '{"id": 1}'.
    """
    try:
        from sqlalchemy import create_engine, text, inspect  # type: ignore
    except ImportError:
        return (
            "Error: SQLAlchemy is not installed.\n"
            "Install it with: pip install sqlalchemy"
        )

    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        return (
            "Error: DATABASE_URL is not set.\n"
            "Add DATABASE_URL=sqlite:///mydb.db (or your DB URL) to your .env file."
        )

    action = (action or "").strip().lower()
    if not action:
        return "Error: 'action' is required."

    # Parse optional bind params
    bind_params: dict = {}
    if params and params.strip():
        import json
        try:
            bind_params = json.loads(params)
            if not isinstance(bind_params, dict):
                return "Error: 'params' must be a JSON object."
        except Exception as e:
            return f"Error parsing params JSON: {e}"

    try:
        engine = create_engine(db_url, pool_pre_ping=True)

        if action == "tables":
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            if not tables:
                return "No tables found in the database."
            return "Tables:\n" + "\n".join(f"  • {t}" for t in sorted(tables))

        if action == "schema":
            if not table:
                return "Error: 'table' is required for schema action."
            inspector = inspect(engine)
            try:
                cols = inspector.get_columns(table)
            except Exception:
                return f"Error: Table '{table}' not found or not accessible."
            lines = [f"Schema for table '{table}':"]
            for col in cols:
                nullable = "" if col.get("nullable", True) else " NOT NULL"
                default  = f"  default={col['default']}" if col.get("default") else ""
                lines.append(f"  {col['name']:<30} {str(col['type']):<20}{nullable}{default}")
            return "\n".join(lines)

        if action in ("query", "explain"):
            if not sql:
                return "Error: 'sql' is required."
            stmt = sql.strip()
            if not re.match(r"^\s*(select|explain|with)\b", stmt, re.IGNORECASE):
                return "Error: Only SELECT / EXPLAIN / WITH statements are allowed for 'query'."
            if action == "explain":
                dialect = engine.dialect.name
                if dialect == "postgresql":
                    stmt = f"EXPLAIN {stmt}"
                elif dialect == "mysql":
                    stmt = f"EXPLAIN {stmt}"
                elif dialect == "sqlite":
                    stmt = f"EXPLAIN QUERY PLAN {stmt}"
            with engine.connect() as conn:
                result = conn.execute(text(stmt), bind_params)
                rows = result.fetchmany(_MAX_ROWS)
                cols = list(result.keys())
            if not rows:
                return "Query returned 0 rows."
            # Format as aligned table
            col_widths = [max(len(str(c)), max((len(str(r[i])) for r in rows), default=0)) for i, c in enumerate(cols)]
            header = "  ".join(str(c).ljust(col_widths[i]) for i, c in enumerate(cols))
            sep    = "  ".join("─" * w for w in col_widths)
            lines  = [header, sep]
            for row in rows:
                lines.append("  ".join(str(row[i]).ljust(col_widths[i]) for i in range(len(cols))))
            if len(rows) == _MAX_ROWS:
                lines.append(f"\n[Showing first {_MAX_ROWS} rows — use LIMIT to narrow results]")
            return "\n".join(lines)

        if action == "execute":
            if not sql:
                return "Error: 'sql' is required."
            stmt = sql.strip()
            # Block dangerous DDL
            if _BLOCKED_DDL.match(stmt):
                if confirm.strip().lower() != "yes":
                    return (
                        f"⚠ Blocked: '{stmt[:60]}...' contains DDL that can destroy data.\n"
                        f"Pass confirm='yes' to proceed."
                    )
            # Require confirmation for any DML mutation
            if confirm.strip().lower() != "yes":
                return (
                    "⚠ DML statements (INSERT/UPDATE/DELETE) require confirm='yes' to protect data.\n"
                    "Pass confirm='yes' to proceed."
                )
            with engine.begin() as conn:
                result = conn.execute(text(stmt), bind_params)
                affected = result.rowcount
            return f"Executed successfully. Rows affected: {affected}"

        return f"Unknown action '{action}'. Use: query, execute, tables, schema, explain."

    except Exception as exc:
        logger.error("sql_db_tool: %s", exc)
        return f"Database error: {exc}"
