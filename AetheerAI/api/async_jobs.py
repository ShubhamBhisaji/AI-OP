"""Shared helpers for Supabase-backed async jobs and queue payloads."""
from __future__ import annotations

import datetime
import os
from typing import Any, Mapping

from integrations.supabase_client import SupabaseClient


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _coerce_int(value: Any, default: int, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


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


def build_queue_payload(
    job_id: str,
    task_type: str,
    task_data: Mapping[str, Any],
    *,
    priority: str = "normal",
    retry_count: int = 0,
    max_retries: int | None = None,
) -> dict[str, Any]:
    normalized_priority = str(priority or "normal").strip().lower() or "normal"
    normalized_retry_count = _coerce_int(retry_count, 0, minimum=0)
    return {
        "jobId": job_id,
        "taskType": task_type,
        "task": dict(task_data),
        "priority": normalized_priority,
        "retryCount": normalized_retry_count,
        "maxRetries": _coerce_int(max_retries, 0, minimum=0) if max_retries is not None else None,
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
        base_metadata = dict(metadata or {})
        base_metadata["retry_count"] = _coerce_int(base_metadata.get("retry_count"), 0, minimum=0)
        if "max_retries" in base_metadata:
            base_metadata["max_retries"] = _coerce_int(base_metadata.get("max_retries"), 0, minimum=0)
        base_metadata["last_queued_at"] = now

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
            "metadata": base_metadata,
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

    def list_stale_running_jobs(self, *, timeout_seconds: int, limit: int = 100) -> list[dict[str, Any]]:
        timeout = _coerce_int(timeout_seconds, 1, minimum=1)
        stale_before = (_utc_now() - datetime.timedelta(seconds=timeout)).isoformat()
        response = self.supabase.query_rows(
            table=self.table_name,
            filters={
                "status": "eq.running",
                "started_at": f"lt.{stale_before}",
            },
            order="started_at.asc",
            limit=_coerce_int(limit, 100, minimum=1),
            use_service_role=True,
        )
        return _rows_from_response(response)

    def mark_running(self, job_id: str, *, retry_count: int | None = None, max_retries: int | None = None) -> None:
        now = _utc_now_iso()
        metadata_updates: dict[str, Any] = {
            "last_started_at": now,
        }
        if retry_count is not None:
            metadata_updates["retry_count"] = _coerce_int(retry_count, 0, minimum=0)
        if max_retries is not None:
            metadata_updates["max_retries"] = _coerce_int(max_retries, 0, minimum=0)

        self._update(
            job_id,
            {
                "status": "running",
                "started_at": now,
                "updated_at": now,
                "error": None,
                "metadata": self._metadata_with_updates(job_id, metadata_updates),
            },
        )

    def mark_completed(self, job_id: str, result: Any) -> None:
        now = _utc_now_iso()
        self._update(
            job_id,
            {
                "status": "completed",
                "result": result,
                "error": None,
                "completed_at": now,
                "updated_at": now,
                "metadata": self._metadata_with_updates(
                    job_id,
                    {
                        "last_completed_at": now,
                    },
                ),
            },
        )

    def mark_failed(self, job_id: str, error_message: str) -> None:
        now = _utc_now_iso()
        self._update(
            job_id,
            {
                "status": "failed",
                "error": str(error_message),
                "completed_at": now,
                "updated_at": now,
                "metadata": self._metadata_with_updates(
                    job_id,
                    {
                        "last_failed_at": now,
                    },
                ),
            },
        )

    def mark_requeued_for_retry(
        self,
        job_id: str,
        *,
        error_message: str,
        retry_count: int,
        max_retries: int,
        reason: str,
    ) -> None:
        now = _utc_now_iso()
        self._update(
            job_id,
            {
                "status": "queued",
                "error": str(error_message),
                "result": None,
                "started_at": None,
                "completed_at": None,
                "updated_at": now,
                "metadata": self._metadata_with_updates(
                    job_id,
                    {
                        "retry_count": _coerce_int(retry_count, 0, minimum=0),
                        "max_retries": _coerce_int(max_retries, 0, minimum=0),
                        "last_failure_reason": reason,
                        "last_failed_at": now,
                        "last_queued_at": now,
                        "dead_lettered": False,
                    },
                ),
            },
        )

    def mark_dead_lettered(
        self,
        job_id: str,
        *,
        error_message: str,
        retry_count: int,
        max_retries: int,
        reason: str,
        dlq_queue: str,
    ) -> None:
        now = _utc_now_iso()
        self._update(
            job_id,
            {
                "status": "failed",
                "error": str(error_message),
                "completed_at": now,
                "updated_at": now,
                "metadata": self._metadata_with_updates(
                    job_id,
                    {
                        "retry_count": _coerce_int(retry_count, 0, minimum=0),
                        "max_retries": _coerce_int(max_retries, 0, minimum=0),
                        "dead_lettered": True,
                        "dead_lettered_at": now,
                        "dead_letter_reason": reason,
                        "dead_letter_queue": str(dlq_queue or "").strip(),
                    },
                ),
            },
        )

    def append_stream_event(
        self,
        job_id: str,
        *,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        now = _utc_now_iso()
        stream_max_events = _coerce_int(
            os.getenv("AETHEER_JOB_STREAM_MAX_EVENTS"),
            100,
            minimum=10,
        )

        row = self.get_job(job_id)
        base_metadata = dict(row.get("metadata") or {}) if isinstance(row, dict) else {}
        existing_events = base_metadata.get("stream_events") if isinstance(base_metadata.get("stream_events"), list) else []
        stream_events = [evt for evt in existing_events if isinstance(evt, dict)]

        event = {
            "ts": now,
            "type": str(event_type or "info"),
            "status": str(status or (row.get("status") if isinstance(row, dict) else "") or ""),
            "payload": dict(payload or {}),
        }
        stream_events.append(event)
        if len(stream_events) > stream_max_events:
            stream_events = stream_events[-stream_max_events:]

        prior_count = _coerce_int(base_metadata.get("stream_event_count"), len(stream_events) - 1, minimum=0)
        metadata_updates = {
            "stream_results": bool(base_metadata.get("stream_results", True)),
            "stream_events": stream_events,
            "stream_event_count": prior_count + 1,
            "last_stream_event_at": now,
        }
        if status is not None:
            metadata_updates["stream_last_status"] = str(status)

        self._update(
            job_id,
            {
                "updated_at": now,
                "metadata": self._metadata_with_updates(job_id, metadata_updates),
            },
        )
        return event

    def cleanup_old_jobs(
        self,
        *,
        retention_hours: int,
        limit: int = 500,
    ) -> int:
        max_rows = _coerce_int(limit, 500, minimum=1)
        retention = _coerce_int(retention_hours, 168, minimum=1)
        cutoff = (_utc_now() - datetime.timedelta(hours=retention)).isoformat()

        response = self.supabase.query_rows(
            table=self.table_name,
            select=self.id_column,
            filters={
                "status": "in.(completed,failed)",
                "completed_at": f"lt.{cutoff}",
            },
            order="completed_at.asc",
            limit=max_rows,
            use_service_role=True,
        )
        rows = _rows_from_response(response)

        deleted = 0
        for row in rows:
            raw_id = row.get(self.id_column)
            if raw_id in (None, ""):
                continue

            self.supabase.delete_rows(
                table=self.table_name,
                filters={self.id_column: f"eq.{raw_id}"},
                use_service_role=True,
            )
            deleted += 1

        return deleted

    def _update(self, job_id: str, values: Mapping[str, Any]) -> None:
        self.supabase.update_rows(
            table=self.table_name,
            values=dict(values),
            filters={self.id_column: f"eq.{job_id}"},
            use_service_role=True,
        )

    def _metadata_with_updates(self, job_id: str, updates: Mapping[str, Any]) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        try:
            existing = self.get_job(job_id)
        except Exception:
            existing = None

        if isinstance(existing, dict) and isinstance(existing.get("metadata"), dict):
            metadata.update(existing["metadata"])

        metadata.update(dict(updates))
        return metadata
