"""Meta Graph API wrapper for Facebook, Instagram, and Messenger."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from integrations.base_client import BaseServiceClient
from integrations.config import MetaConfig
from integrations.errors import ConfigurationError
from integrations.http import HTTPTransport


class MetaAPIClient(BaseServiceClient):
    """High-level helper for Meta Graph API operations."""

    service_name = "meta"

    def __init__(
        self,
        config: MetaConfig | None = None,
        *,
        transport: HTTPTransport | None = None,
    ) -> None:
        self.config = config or MetaConfig.from_env()
        super().__init__(
            transport=transport,
            timeout_seconds=self.config.timeout_seconds,
        )

    def get_managed_pages(self) -> Any:
        return self._graph_request(
            "GET",
            "/me/accounts",
            expected_statuses=(200,),
            error_context="Meta managed pages fetch failed",
        )

    def publish_page_post(
        self,
        *,
        message: str,
        page_id: str | None = None,
        link: str = "",
    ) -> Any:
        resolved_page_id = page_id or self.config.default_page_id
        if not resolved_page_id:
            raise ConfigurationError("META_DEFAULT_PAGE_ID is required for page publishing")

        data = {"message": message}
        if link:
            data["link"] = link

        return self._graph_request(
            "POST",
            f"/{resolved_page_id}/feed",
            data=data,
            expected_statuses=(200,),
            error_context="Meta page post publish failed",
        )

    def send_messenger_text(
        self,
        *,
        recipient_id: str,
        text: str,
        page_id: str | None = None,
    ) -> Any:
        resolved_page_id = page_id or self.config.default_page_id
        if not resolved_page_id:
            raise ConfigurationError("META_DEFAULT_PAGE_ID is required for Messenger sends")

        payload = {
            "messaging_type": "RESPONSE",
            "recipient": {"id": recipient_id},
            "message": {"text": text},
        }

        return self._graph_request(
            "POST",
            f"/{resolved_page_id}/messages",
            json_body=payload,
            expected_statuses=(200,),
            error_context="Meta Messenger send failed",
        )

    def create_instagram_media_container(
        self,
        *,
        image_url: str,
        caption: str = "",
        instagram_business_id: str | None = None,
    ) -> Any:
        ig_id = instagram_business_id or self.config.default_instagram_business_id
        if not ig_id:
            raise ConfigurationError(
                "META_DEFAULT_INSTAGRAM_BUSINESS_ID is required for Instagram publishing"
            )

        data: dict[str, str] = {"image_url": image_url}
        if caption:
            data["caption"] = caption

        return self._graph_request(
            "POST",
            f"/{ig_id}/media",
            data=data,
            expected_statuses=(200,),
            error_context="Meta Instagram media container creation failed",
        )

    def publish_instagram_media(
        self,
        *,
        creation_id: str,
        instagram_business_id: str | None = None,
    ) -> Any:
        ig_id = instagram_business_id or self.config.default_instagram_business_id
        if not ig_id:
            raise ConfigurationError(
                "META_DEFAULT_INSTAGRAM_BUSINESS_ID is required for Instagram publishing"
            )

        return self._graph_request(
            "POST",
            f"/{ig_id}/media_publish",
            data={"creation_id": creation_id},
            expected_statuses=(200,),
            error_context="Meta Instagram media publish failed",
        )

    def publish_instagram_image(
        self,
        *,
        image_url: str,
        caption: str,
        instagram_business_id: str | None = None,
    ) -> Any:
        container = self.create_instagram_media_container(
            image_url=image_url,
            caption=caption,
            instagram_business_id=instagram_business_id,
        )
        creation_id = str((container or {}).get("id") or "")
        if not creation_id:
            raise ConfigurationError("Meta API did not return an Instagram creation_id")

        return self.publish_instagram_media(
            creation_id=creation_id,
            instagram_business_id=instagram_business_id,
        )

    def get_page_insights(
        self,
        *,
        metrics: Sequence[str],
        page_id: str | None = None,
        period: str = "day",
    ) -> Any:
        resolved_page_id = page_id or self.config.default_page_id
        if not resolved_page_id:
            raise ConfigurationError("META_DEFAULT_PAGE_ID is required for page insights")

        return self._graph_request(
            "GET",
            f"/{resolved_page_id}/insights",
            params={"metric": ",".join(metrics), "period": period},
            expected_statuses=(200,),
            error_context="Meta page insights fetch failed",
        )

    def get_instagram_insights(
        self,
        *,
        metrics: Sequence[str],
        instagram_business_id: str | None = None,
        period: str = "day",
    ) -> Any:
        ig_id = instagram_business_id or self.config.default_instagram_business_id
        if not ig_id:
            raise ConfigurationError(
                "META_DEFAULT_INSTAGRAM_BUSINESS_ID is required for IG insights"
            )

        return self._graph_request(
            "GET",
            f"/{ig_id}/insights",
            params={"metric": ",".join(metrics), "period": period},
            expected_statuses=(200,),
            error_context="Meta Instagram insights fetch failed",
        )

    def _graph_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        data: Any = None,
        expected_statuses: tuple[int, ...] = (200,),
        error_context: str,
    ) -> Any:
        merged_params = dict(params or {})
        merged_params["access_token"] = self.config.access_token

        return self._request(
            method,
            f"{self.config.graph_base_url.rstrip('/')}{path}",
            params=merged_params,
            json_body=json_body,
            data=data,
            expected_statuses=expected_statuses,
            error_context=error_context,
        )
