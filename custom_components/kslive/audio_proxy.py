"""Audio-only HTTP relay for players that cannot consume video-bearing HLS."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Final, override

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.util.hass_dict import HassKey

from .streaming import ffmpeg_audio_arguments

_LOGGER = logging.getLogger(__name__)

DATA_AUDIO_PROXY: HassKey[KSLiveAudioProxy] = HassKey("kslive.audio_proxy")

_CHUNK_SIZE: Final = 64 * 1024
_FIRST_AUDIO_TIMEOUT: Final = 20
_MAX_SESSIONS: Final = 16
_SESSION_TTL: Final = 8 * 60 * 60


@dataclass(slots=True)
class _RelaySession:
    """A private, short-lived mapping from a URL token to a KSLive stream."""

    target_entity_id: str
    source_url: str
    created_at: float
    process: asyncio.subprocess.Process | None = None


class KSLiveAudioProxy:
    """Transcode KSLive HLS to an audio-only MP3 stream on demand."""

    def __init__(self, hass: HomeAssistant, ffmpeg_binary: str) -> None:
        self.hass = hass
        self._ffmpeg_binary = ffmpeg_binary
        self._sessions: dict[str, _RelaySession] = {}
        self._target_tokens: dict[str, str] = {}

    async def async_create_path(self, target_entity_id: str, source_url: str) -> str:
        """Create a secret local relay path, replacing an older target session."""
        await self.async_stop_target(target_entity_id)
        await self._async_prune()

        token = secrets.token_urlsafe(32)
        self._sessions[token] = _RelaySession(
            target_entity_id=target_entity_id,
            source_url=source_url,
            created_at=time.monotonic(),
        )
        self._target_tokens[target_entity_id] = token
        return f"/api/kslive/audio/{token}.mp3"

    async def async_stop_target(self, target_entity_id: str) -> None:
        """Revoke and stop the relay assigned to a media player."""
        token = self._target_tokens.pop(target_entity_id, None)
        if token is None:
            return
        session = self._sessions.pop(token, None)
        if session is not None:
            await self._async_stop_process(session.process)

    async def async_shutdown(self) -> None:
        """Stop all relay processes during Home Assistant shutdown."""
        sessions = tuple(self._sessions.values())
        self._sessions.clear()
        self._target_tokens.clear()
        await asyncio.gather(
            *(self._async_stop_process(session.process) for session in sessions)
        )

    def session(self, token: str) -> _RelaySession | None:
        """Resolve a non-expired private relay session."""
        session = self._sessions.get(token)
        if session is None:
            return None
        if time.monotonic() - session.created_at > _SESSION_TTL:
            return None
        return session

    async def async_stream(
        self, request: web.Request, session: _RelaySession
    ) -> web.StreamResponse:
        """Run FFmpeg and stream only the source audio to the requesting player."""
        await self._async_stop_process(session.process)
        process = await asyncio.create_subprocess_exec(
            self._ffmpeg_binary,
            *ffmpeg_audio_arguments(session.source_url),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        session.process = process
        assert process.stdout is not None
        response = web.StreamResponse(headers=_audio_headers())

        try:
            first_chunk = await asyncio.wait_for(
                process.stdout.read(_CHUNK_SIZE), timeout=_FIRST_AUDIO_TIMEOUT
            )
            if not first_chunk:
                raise web.HTTPBadGateway(text="KSLive audio relay did not start")

            response.enable_chunked_encoding()
            await response.prepare(request)
            await response.write(first_chunk)

            while chunk := await process.stdout.read(_CHUNK_SIZE):
                await response.write(chunk)

            with suppress(ConnectionResetError, RuntimeError):
                await response.write_eof()
            return response
        except TimeoutError as err:
            raise web.HTTPGatewayTimeout(
                text="KSLive audio relay timed out"
            ) from err
        except (ConnectionResetError, BrokenPipeError):
            _LOGGER.debug(
                "KSLive audio relay client disconnected for %s",
                session.target_entity_id,
            )
            return response
        finally:
            await self._async_stop_process(process)
            if session.process is process:
                session.process = None

    async def _async_prune(self) -> None:
        now = time.monotonic()
        expired = [
            token
            for token, session in self._sessions.items()
            if now - session.created_at > _SESSION_TTL
        ]
        excess = max(0, len(self._sessions) - _MAX_SESSIONS + 1)
        if excess:
            oldest = sorted(
                self._sessions,
                key=lambda token: self._sessions[token].created_at,
            )[:excess]
            expired.extend(oldest)

        for token in dict.fromkeys(expired):
            session = self._sessions.pop(token, None)
            if session is None:
                continue
            if self._target_tokens.get(session.target_entity_id) == token:
                self._target_tokens.pop(session.target_entity_id, None)
            await self._async_stop_process(session.process)

    @staticmethod
    async def _async_stop_process(
        process: asyncio.subprocess.Process | None,
    ) -> None:
        if process is None or process.returncode is not None:
            return
        with suppress(ProcessLookupError):
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()


class KSLiveAudioView(HomeAssistantView):
    """Serve a token-protected, audio-only stream to LAN speakers."""

    name = "api:kslive:audio"
    url = "/api/kslive/audio/{token}.mp3"
    requires_auth = False

    def __init__(self, proxy: KSLiveAudioProxy) -> None:
        self._proxy = proxy

    @override
    async def head(self, request: web.Request, token: str) -> web.Response:
        """Allow a speaker to inspect the stream without starting FFmpeg."""
        if self._proxy.session(token) is None:
            raise web.HTTPNotFound
        return web.Response(headers=_audio_headers())

    @override
    async def get(self, request: web.Request, token: str) -> web.StreamResponse:
        """Return the relayed KSLive audio."""
        session = self._proxy.session(token)
        if session is None:
            raise web.HTTPNotFound
        return await self._proxy.async_stream(request, session)


def _audio_headers() -> dict[str, str]:
    return {
        "Accept-Ranges": "none",
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Content-Type": "audio/mpeg",
        "Pragma": "no-cache",
    }
