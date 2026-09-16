"""Async client for the KSLive subscriber API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from aiohttp import ClientError, ClientResponse, ClientSession

from .const import API_BASE_URL, APP_PLATFORM, APP_VERSION, STORE_ID, STORE_TOKEN
from .models import find_stream_url

TokenCallback = Callable[[dict[str, Any]], Awaitable[None]]


class KSLiveApiError(Exception):
    """Base KSLive API error."""


class KSLiveAuthenticationError(KSLiveApiError):
    """KSLive rejected the account or refresh token."""


class KSLivePlaybackError(KSLiveApiError):
    """No subscriber playback URL could be obtained."""


class KSLiveApiClient:
    """Small client for the official KSLive subscriber app API."""

    def __init__(
        self,
        session: ClientSession,
        *,
        access_token: str | None = None,
        refresh_token: str | None = None,
        expires_at: int | float | None = None,
        device_id: str | None = None,
        token_callback: TokenCallback | None = None,
    ) -> None:
        self._session = session
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._expires_at = float(expires_at or 0)
        self._device_id = device_id
        self._token_callback = token_callback

    @property
    def _base_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Store-Token": STORE_TOKEN,
            "X-Store-Id": STORE_ID,
            "X-App-Version": APP_VERSION,
            "X-App-Platform": APP_PLATFORM,
            "X-Locale": "en",
        }

    async def async_login(self, email: str, password: str) -> dict[str, Any]:
        """Exchange credentials for short-lived subscriber tokens."""
        payload: dict[str, Any] = {"email": email, "password": password}
        if self._device_id:
            payload.update(
                {
                    "device_id": self._device_id,
                    "device_name": "Home Assistant",
                    "device_unique_identifier": self._device_id,
                }
            )
        response = await self._raw_request("POST", "/sessions", json=payload)
        data = await self._json(response)
        self._set_auth(data.get("auth"))
        return data

    async def async_refresh(self) -> None:
        """Refresh the subscriber session."""
        if not self._refresh_token:
            raise KSLiveAuthenticationError("No refresh token is available")
        response = await self._raw_request(
            "POST", "/sessions/refresh", json={"refresh_token": self._refresh_token}
        )
        data = await self._json(response)
        await self._async_set_auth(data.get("auth"))

    async def async_profile(self) -> dict[str, Any]:
        """Return the subscriber profile."""
        return await self._request_json("GET", "/profile")

    async def async_search(self, title: str) -> dict[str, Any]:
        """Search the member catalog."""
        return await self._request_json("GET", "/contents", params={"title": title})

    async def async_content(self, content_id: int) -> dict[str, Any]:
        """Return full metadata for one catalog item."""
        return await self._request_json("GET", f"/contents/{content_id}")

    async def async_playback_url(self, content_id: int) -> str:
        """Resolve a fresh subscriber stream URL for a content item."""
        # The playlist endpoint is what the official subscriber app uses to
        # obtain fresh, entitlement-checked HLS URLs. Content metadata alone
        # intentionally does not contain the protected playback source.
        playlist = await self._request_value(
            "GET", f"/contents/{content_id}/playlist"
        )
        if url := find_stream_url(playlist):
            return url
        raise KSLivePlaybackError("KSLive did not return a playable audio stream")

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        retry: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        value = await self._request_value(method, path, retry=retry, **kwargs)
        if not isinstance(value, dict):
            raise KSLiveApiError("KSLive returned an unexpected response")
        return value

    async def _request_value(
        self,
        method: str,
        path: str,
        *,
        retry: bool = True,
        **kwargs: Any,
    ) -> Any:
        """Request any JSON value, refreshing an expired session once."""
        if self._token_expiring:
            await self.async_refresh()
        response = await self._raw_request(method, path, authenticated=True, **kwargs)
        if response.status == 401 and retry:
            await response.read()
            await self.async_refresh()
            return await self._request_value(method, path, retry=False, **kwargs)
        return await self._json_value(response)

    async def _raw_request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = False,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> ClientResponse:
        request_headers = self._base_headers
        request_headers.update(headers or {})
        if authenticated and self._access_token:
            request_headers["Authorization"] = f"Bearer {self._access_token}"
        try:
            return await self._session.request(
                method,
                f"{API_BASE_URL}{path}",
                headers=request_headers,
                timeout=30,
                **kwargs,
            )
        except (ClientError, TimeoutError) as err:
            raise KSLiveApiError("Unable to reach KSLive") from err

    async def _json(self, response: ClientResponse) -> dict[str, Any]:
        data = await self._json_value(response)
        if not isinstance(data, dict):
            raise KSLiveApiError("KSLive returned an unexpected response")
        return data

    async def _json_value(self, response: ClientResponse) -> Any:
        if response.status in {401, 403}:
            await response.read()
            raise KSLiveAuthenticationError("KSLive rejected the subscriber session")
        if response.status >= 400:
            await response.read()
            raise KSLiveApiError(f"KSLive returned HTTP {response.status}")
        try:
            data = await response.json(content_type=None)
        except (ValueError, ClientError) as err:
            raise KSLiveApiError("KSLive returned an invalid response") from err
        return data

    @property
    def _token_expiring(self) -> bool:
        return bool(
            self._refresh_token
            and self._expires_at
            and datetime.now(UTC).timestamp() >= self._expires_at - 60
        )

    def _set_auth(self, auth: Any) -> None:
        if not isinstance(auth, dict) or not auth.get("access_token") or not auth.get(
            "refresh_token"
        ):
            raise KSLiveAuthenticationError("KSLive did not return subscriber tokens")
        self._access_token = str(auth["access_token"])
        self._refresh_token = str(auth["refresh_token"])
        raw_exp = auth.get("exp")
        self._expires_at = self._normalize_expiry(raw_exp)

    async def _async_set_auth(self, auth: Any) -> None:
        self._set_auth(auth)
        if self._token_callback:
            await self._token_callback(self.auth_data)

    @staticmethod
    def _normalize_expiry(raw_exp: Any) -> float:
        try:
            value = float(raw_exp)
        except (TypeError, ValueError):
            return (datetime.now(UTC) + timedelta(minutes=50)).timestamp()
        # Some APIs return seconds-until-expiry; JWT expiry values are epochs.
        if value < 10_000_000_000:
            if value < datetime.now(UTC).timestamp() - 86_400:
                return datetime.now(UTC).timestamp() + value
        return value

    @property
    def auth_data(self) -> dict[str, Any]:
        """Return the current non-password authentication state."""
        return {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "token_expires_at": self._expires_at,
        }
