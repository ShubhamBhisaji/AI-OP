"""Supabase wrapper for auth, data operations, and realtime subscriptions."""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote

from integrations.base_client import BaseServiceClient
from integrations.config import SupabaseConfig
from integrations.errors import ConfigurationError, IntegrationError
from integrations.http import HTTPTransport


class SupabaseClient(BaseServiceClient):
    """High-level Supabase helper for auth, storage, and realtime."""

    service_name = "supabase"

    def __init__(
        self,
        config: SupabaseConfig | None = None,
        *,
        transport: HTTPTransport | None = None,
    ) -> None:
        self.config = config or SupabaseConfig.from_env()
        super().__init__(
            transport=transport,
            timeout_seconds=self.config.timeout_seconds,
        )
        self._access_token = ""
        self._refresh_token = ""

    # ------------------------------------------------------------------
    # Auth operations
    # ------------------------------------------------------------------

    def sign_up(
        self,
        *,
        email: str,
        password: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new user via the Admin API (service role) to bypass rate limits
        and email confirmation requirements."""
        payload: dict[str, Any] = {
            "email": email,
            "password": password,
            "email_confirm": True,
        }
        if metadata:
            payload["user_metadata"] = dict(metadata)

        response = self._request(
            "POST",
            f"{self.config.auth_url}/admin/users",
            headers=self._service_headers(use_service_role=True),
            json_body=payload,
            expected_statuses=(200, 201),
            error_context="Supabase sign-up failed",
        )
        # Admin API returns {"user": {...}} — normalise to match signup shape
        result = _as_dict(response)
        if "user" not in result and "id" in result:
            result = {"user": result}
        return result

    def sign_in_with_password(self, *, email: str, password: str) -> dict[str, Any]:
        response = self._request(
            "POST",
            f"{self.config.auth_url}/token",
            headers=self._service_headers(use_service_role=False),
            params={"grant_type": "password"},
            json_body={"email": email, "password": password},
            expected_statuses=(200,),
            error_context="Supabase sign-in failed",
        )

        session = _as_dict(response)
        self._access_token = str(session.get("access_token") or "")
        self._refresh_token = str(session.get("refresh_token") or "")
        return session

    def refresh_session(self, refresh_token: str | None = None) -> dict[str, Any]:
        token = refresh_token or self._refresh_token
        if not token:
            raise ConfigurationError(
                "Missing refresh token. Call sign_in_with_password first or pass refresh_token."
            )

        response = self._request(
            "POST",
            f"{self.config.auth_url}/token",
            headers=self._service_headers(use_service_role=False),
            params={"grant_type": "refresh_token"},
            json_body={"refresh_token": token},
            expected_statuses=(200,),
            error_context="Supabase refresh-session failed",
        )

        session = _as_dict(response)
        self._access_token = str(session.get("access_token") or self._access_token)
        self._refresh_token = str(session.get("refresh_token") or token)
        return session

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------

    def insert_row(
        self,
        *,
        table: str,
        payload: Mapping[str, Any] | list[Mapping[str, Any]],
        use_service_role: bool = True,
        upsert: bool = False,
    ) -> Any:
        headers = self._service_headers(use_service_role=use_service_role)
        headers["Prefer"] = "return=representation"
        if upsert:
            headers["Prefer"] = "return=representation,resolution=merge-duplicates"

        return self._request(
            "POST",
            f"{self.config.rest_url}/{table}",
            headers=headers,
            json_body=payload,
            expected_statuses=(200, 201),
            error_context=f"Supabase insert failed for table '{table}'",
        )

    def query_rows(
        self,
        *,
        table: str,
        select: str = "*",
        filters: Mapping[str, str] | None = None,
        limit: int | None = None,
        order: str | None = None,
        use_service_role: bool = False,
    ) -> Any:
        params: dict[str, Any] = {"select": select}
        if filters:
            params.update(filters)
        if limit is not None:
            params["limit"] = str(limit)
        if order:
            params["order"] = order

        return self._request(
            "GET",
            f"{self.config.rest_url}/{table}",
            headers=self._service_headers(use_service_role=use_service_role),
            params=params,
            expected_statuses=(200,),
            error_context=f"Supabase query failed for table '{table}'",
        )

    def update_rows(
        self,
        *,
        table: str,
        values: Mapping[str, Any],
        filters: Mapping[str, str],
        use_service_role: bool = True,
    ) -> Any:
        if not filters:
            raise ConfigurationError(
                "update_rows requires at least one filter to avoid full-table updates."
            )

        headers = self._service_headers(use_service_role=use_service_role)
        headers["Prefer"] = "return=representation"

        return self._request(
            "PATCH",
            f"{self.config.rest_url}/{table}",
            headers=headers,
            params=filters,
            json_body=dict(values),
            expected_statuses=(200, 204),
            error_context=f"Supabase update failed for table '{table}'",
        )

    def delete_rows(
        self,
        *,
        table: str,
        filters: Mapping[str, str],
        use_service_role: bool = True,
    ) -> Any:
        if not filters:
            raise ConfigurationError(
                "delete_rows requires at least one filter to avoid full-table deletes."
            )

        headers = self._service_headers(use_service_role=use_service_role)
        headers["Prefer"] = "return=representation"

        return self._request(
            "DELETE",
            f"{self.config.rest_url}/{table}",
            headers=headers,
            params=filters,
            expected_statuses=(200, 204),
            error_context=f"Supabase delete failed for table '{table}'",
        )

    def call_rpc(
        self,
        *,
        function_name: str,
        arguments: Mapping[str, Any] | None = None,
        use_service_role: bool = True,
    ) -> Any:
        return self._request(
            "POST",
            f"{self.config.rest_url}/rpc/{function_name}",
            headers=self._service_headers(use_service_role=use_service_role),
            json_body=dict(arguments or {}),
            expected_statuses=(200,),
            error_context=f"Supabase RPC failed for function '{function_name}'",
        )

    # ------------------------------------------------------------------
    # Realtime operations
    # ------------------------------------------------------------------

    def build_realtime_subscription(
        self,
        *,
        table: str,
        event: str = "*",
        schema: str | None = None,
        channel: str = "realtime",
        access_token: str | None = None,
    ) -> dict[str, Any]:
        schema_name = schema or self.config.schema
        topic = f"realtime:{schema_name}:{table}"
        ws_url = (
            f"{self.config.realtime_websocket_url}"
            f"?apikey={quote(self.config.anon_key)}&vsn=1.0.0"
        )

        payload: dict[str, Any] = {
            "topic": topic,
            "event": "phx_join",
            "payload": {
                "config": {
                    "broadcast": {"self": True},
                    "presence": {"key": channel},
                    "postgres_changes": [
                        {
                            "event": event,
                            "schema": schema_name,
                            "table": table,
                        }
                    ],
                }
            },
            "ref": "1",
        }

        token = access_token or self._access_token
        if token:
            payload["payload"]["access_token"] = token

        return {
            "websocket_url": ws_url,
            "join_payload": payload,
        }

    def listen_realtime(
        self,
        *,
        table: str,
        event: str = "*",
        schema: str | None = None,
        channel: str = "realtime",
        listen_seconds: int = 30,
        max_events: int = 20,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        access_token: str | None = None,
    ) -> list[dict[str, Any]]:
        """Listen to realtime events (requires websocket-client package)."""
        try:
            import websocket  # type: ignore
        except ImportError as exc:
            raise IntegrationError(
                "websocket-client package is required for Supabase realtime subscriptions"
            ) from exc

        subscription = self.build_realtime_subscription(
            table=table,
            event=event,
            schema=schema,
            channel=channel,
            access_token=access_token,
        )

        events: list[dict[str, Any]] = []
        ws = websocket.create_connection(
            subscription["websocket_url"],
            timeout=self.config.timeout_seconds,
        )

        try:
            ws.send(json.dumps(subscription["join_payload"]))
            started = time.monotonic()

            while (time.monotonic() - started) < listen_seconds and len(events) < max_events:
                raw_message = ws.recv()
                if not raw_message:
                    continue
                try:
                    decoded = json.loads(raw_message)
                except json.JSONDecodeError:
                    self._log.debug("Supabase realtime message was not valid JSON: %s", raw_message)
                    continue

                if isinstance(decoded, dict):
                    events.append(decoded)
                    if on_event is not None:
                        on_event(decoded)
        finally:
            ws.close()

        return events

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _service_headers(self, *, use_service_role: bool) -> dict[str, str]:
        api_key = self.config.anon_key
        if use_service_role and self.config.service_role_key:
            api_key = self.config.service_role_key

        bearer = self._access_token if self._access_token and not use_service_role else api_key
        return {
            "apikey": api_key,
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
        }


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {"data": value}
