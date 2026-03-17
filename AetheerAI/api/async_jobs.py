"""Shared helpers for Supabase-backed async jobs and queue payloads."""
from __future__ import annotations

import datetime
import os
from typing import Any, Mapping

from integrations.supabase_client import SupabaseClient


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


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


def build_queue_payload(job_id: str, task_type: str, task_data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "jobId": job_id,
        "taskType": task_type,
        "task": dict(task_data),
        "enqueuedAt": _utc_now_iso(),
    }


class SupabaseJobStore:
    """CRUD helpers for async job rows in Supabase."""

    def __init__(
        self,
        *,
        supabase: SupabaseClient | None = None,
        table_name: str | None = None,
        id_column: str | None = None,
    ) -> None:
        self.supabase = supabase or SupabaseClient()
        self.table_name = table_name or os.getenv("SUPABASE_JOBS_TABLE", "ai_jobs")
        self.id_column = id_column or os.getenv("SUPABASE_JOBS_ID_COLUMN", "id")

    def create_job(
        self,
        *,
        job_id: str,
        task_type: str,
        task_payload: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _utc_now_iso()
        row: dict[str, Any] = {
            self.id_column: job_id,
            "status": "queued",
            "task_type": task_type,
            "task_payload": dict(task_payload),
            "result": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "completed_at": None,
            "metadata": dict(metadata or {}),
        }
        response = self.supabase.insert_row(
            table=self.table_name,
            payload=row,
            use_service_role=True,
        )
        rows = _rows_from_response(response)
        return rows[0] if rows else row

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        response = self.supabase.query_rows(
            table=self.table_name,
            filters={self.id_column: f"eq.{job_id}"},
            limit=1,
            use_service_role=True,
        )
        rows = _rows_from_response(response)
        if not rows:
            return None
        return rows[0]

    def mark_running(self, job_id: str) -> None:
        self._update(
            job_id,
            {
                "status": "running",
                "started_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "error": None,
            },
        )

    def mark_completed(self, job_id: str, result: Any) -> None:
        self._update(
            job_id,
            {
                "status": "completed",
                "result": result,
                "error": None,
                "completed_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
            },
        )

    def mark_failed(self, job_id: str, error_message: str) -> None:
        self._update(
            job_id,
            {
                "status": "failed",
                "error": str(error_message),
                "completed_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
            },
        )

    def _update(self, job_id: str, values: Mapping[str, Any]) -> None:
        self.supabase.update_rows(
            table=self.table_name,
            values=dict(values),
            filters={self.id_column: f"eq.{job_id}"},
            use_service_role=True,
        )
