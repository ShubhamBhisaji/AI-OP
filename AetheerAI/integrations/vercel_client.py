"""Vercel API wrapper for projects, deployments, and environment variables."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from integrations.base_client import BaseServiceClient
from integrations.config import VercelConfig
from integrations.http import HTTPTransport


class VercelClient(BaseServiceClient):
    """High-level helper for Vercel project and deployment management."""

    service_name = "vercel"

    def __init__(
        self,
        config: VercelConfig | None = None,
        *,
        transport: HTTPTransport | None = None,
    ) -> None:
        self.config = config or VercelConfig.from_env()
        super().__init__(
            transport=transport,
            timeout_seconds=self.config.timeout_seconds,
        )

    def get_current_user(self) -> Any:
        return self._request(
            "GET",
            self._url("/v2/user"),
            headers=self._headers(),
            params=self._with_team({}),
            expected_statuses=(200,),
            error_context="Vercel user profile fetch failed",
        )

    def list_projects(self, *, limit: int = 20) -> Any:
        return self._request(
            "GET",
            self._url("/v9/projects"),
            headers=self._headers(),
            params=self._with_team({"limit": str(limit)}),
            expected_statuses=(200,),
            error_context="Vercel project listing failed",
        )

    def create_project(
        self,
        *,
        name: str,
        framework: str = "nextjs",
        root_directory: str = "",
        git_repository: dict[str, Any] | None = None,
    ) -> Any:
        payload: dict[str, Any] = {
            "name": name,
            "framework": framework,
        }
        if root_directory:
            payload["rootDirectory"] = root_directory
        if git_repository:
            payload["gitRepository"] = git_repository

        return self._request(
            "POST",
            self._url("/v9/projects"),
            headers=self._headers(),
            params=self._with_team({}),
            json_body=payload,
            expected_statuses=(200, 201),
            error_context="Vercel project creation failed",
        )

    def create_git_deployment(
        self,
        *,
        name: str,
        repo: str,
        branch: str = "main",
        project_id: str = "",
        production: bool = True,
    ) -> Any:
        payload: dict[str, Any] = {
            "name": name,
            "target": "production" if production else "preview",
            "gitSource": {
                "type": "github",
                "repo": repo,
                "ref": branch,
            },
        }

        resolved_project_id = project_id or self.config.project_id
        if resolved_project_id:
            payload["project"] = resolved_project_id

        return self._request(
            "POST",
            self._url("/v13/deployments"),
            headers=self._headers(),
            params=self._with_team({}),
            json_body=payload,
            expected_statuses=(200, 201),
            error_context="Vercel deployment creation failed",
        )

    def list_deployments(
        self,
        *,
        limit: int = 20,
        project_id: str = "",
        target: str = "",
    ) -> Any:
        params: dict[str, Any] = {"limit": str(limit)}

        resolved_project_id = project_id or self.config.project_id
        if resolved_project_id:
            params["projectId"] = resolved_project_id
        if target:
            params["target"] = target

        return self._request(
            "GET",
            self._url("/v6/deployments"),
            headers=self._headers(),
            params=self._with_team(params),
            expected_statuses=(200,),
            error_context="Vercel deployment listing failed",
        )

    def get_deployment(self, *, deployment_id: str) -> Any:
        return self._request(
            "GET",
            self._url(f"/v13/deployments/{deployment_id}"),
            headers=self._headers(),
            params=self._with_team({}),
            expected_statuses=(200,),
            error_context="Vercel deployment fetch failed",
        )

    def upsert_project_env_var(
        self,
        *,
        project_id: str,
        key: str,
        value: str,
        targets: Sequence[str] = ("production",),
        env_type: str = "encrypted",
    ) -> Any:
        payload = {
            "key": key,
            "value": value,
            "target": list(targets),
            "type": env_type,
        }

        return self._request(
            "POST",
            self._url(f"/v10/projects/{project_id}/env"),
            headers=self._headers(),
            params=self._with_team({}),
            json_body=payload,
            expected_statuses=(200, 201),
            error_context="Vercel environment variable upsert failed",
        )

    def _url(self, path: str) -> str:
        return f"{self.config.api_base_url.rstrip('/')}{path}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_token}",
            "Content-Type": "application/json",
        }

    def _with_team(self, params: dict[str, Any]) -> dict[str, Any]:
        with_team = dict(params)
        if self.config.team_id:
            with_team["teamId"] = self.config.team_id
        return with_team
