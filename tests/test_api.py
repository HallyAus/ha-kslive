"""Tests for the KSLive API client."""

from __future__ import annotations

import asyncio
from typing import Any

from conftest import load_module

load_module("const")
load_module("models")
api = load_module("api")


class FakeResponse:
    """Minimal aiohttp response stand-in."""

    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status = status

    async def json(self, content_type=None) -> Any:
        return self._payload

    async def read(self) -> bytes:
        return b""


class FakeSession:
    """Record requests and return queued responses."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_playback_uses_entitlement_checked_playlist() -> None:
    session = FakeSession(
        [FakeResponse([{"is_accessible": True, "hls": "https://stream.mux.com/x.m3u8"}])]
    )
    client = api.KSLiveApiClient(
        session,
        access_token="access",
        refresh_token="refresh",
        expires_at=4_102_444_800,
    )
    result = asyncio.run(client.async_playback_url(42))
    assert result == "https://stream.mux.com/x.m3u8"
    assert session.calls[0][0] == "GET"
    assert session.calls[0][1].endswith("/contents/42/playlist")
    assert session.calls[0][2]["headers"]["Authorization"] == "Bearer access"


def test_login_exposes_tokens_but_not_password() -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "user": {"subscribed": True},
                    "auth": {
                        "access_token": "access",
                        "refresh_token": "refresh",
                        "exp": 4_102_444_800,
                    },
                },
                status=201,
            )
        ]
    )
    client = api.KSLiveApiClient(session, device_id="device")
    asyncio.run(client.async_login("member@example.com", "secret"))
    assert client.auth_data == {
        "access_token": "access",
        "refresh_token": "refresh",
        "token_expires_at": 4_102_444_800,
    }
    assert "password" not in client.auth_data


def test_concurrent_wake_requests_rotate_expired_token_only_once() -> None:
    async def run():
        class SlowSession(FakeSession):
            async def request(self, method, url, **kwargs):
                await asyncio.sleep(0)
                return await super().request(method, url, **kwargs)

        session = SlowSession([
            FakeResponse({"auth": {
                "access_token": "new-access", "refresh_token": "new-refresh",
                "exp": 4_102_444_800,
            }}),
            FakeResponse({"contents": []}),
            FakeResponse({"contents": []}),
        ])
        client = api.KSLiveApiClient(
            session, access_token="old", refresh_token="old-refresh", expires_at=1,
        )
        await asyncio.gather(client.async_search("Audio"), client.async_search("Audio"))
        assert len([c for c in session.calls if c[1].endswith("/sessions/refresh")]) == 1
        assert all(
            c[2]["headers"]["Authorization"] == "Bearer new-access"
            for c in session.calls if c[0] == "GET"
        )
    asyncio.run(run())
