"""KSLive data coordinator and playback orchestration."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from datetime import UTC, datetime

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.components.media_player import async_process_play_media_url
from homeassistant.components.media_player.const import SERVICE_PLAY_MEDIA
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import KSLiveApiClient, KSLiveApiError, KSLiveAuthenticationError, KSLivePlaybackError
from .audio_proxy import KSLiveAudioProxy
from .const import (
    ALL_SPEAKERS_SOURCE,
    CONF_MEDIA_PLAYERS,
    CONF_SEARCH_QUERY,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SEARCH_QUERY,
    NAME,
)
from .equalizer import KSLiveEqualizer
from .models import KSLiveCatalog, parse_catalog
from .output_names import first_output_name
from .playback_state import PLAYBACK_START_GRACE, OutputSession, owns_media_url
from .streaming import needs_audio_relay


class KSLiveCoordinator(DataUpdateCoordinator[KSLiveCatalog]):
    """Fetch catalog updates and send audio to Home Assistant players."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: KSLiveApiClient,
        audio_proxy: KSLiveAudioProxy,
        equalizer: KSLiveEqualizer,
    ) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=NAME,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.entry = entry
        self.client = client
        self.audio_proxy = audio_proxy
        self.equalizer = equalizer
        self.last_content_id: int | None = None
        self.last_targets: tuple[str, ...] = ()
        self._selected_output_key: str | None = None
        self._output_store = Store[dict[str, str]](
            hass, 1, f"kslive.{entry.entry_id}.output"
        )
        self._sessions: dict[str, OutputSession] = {}
        self._cleanup_tasks: dict[str, asyncio.Task[None]] = {}
        self._play_lock = asyncio.Lock()
        self._play_task: asyncio.Task[None] | None = None
        self._pending_key: tuple[int, tuple[str, ...]] | None = None
        self._output_labels: dict[str, str] = {}
        self._unsub_state = None
        self._closing = False

    def start_tracking(self) -> None:
        """Track configured outputs and service overrides through one listener."""
        self.output_sources
        self._unsub_state = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED, self._async_output_state_changed
        )

    @callback
    def _async_output_state_changed(self, event: Event) -> None:
        target = event.data.get("entity_id")
        if target not in self._sessions and target not in self.configured_players:
            return
        self.output_state_changed()
        self.async_update_listeners()

    async def _async_update_data(self) -> KSLiveCatalog:
        try:
            payload = await self.client.async_search(
                self.entry.options.get(CONF_SEARCH_QUERY, DEFAULT_SEARCH_QUERY)
            )
        except KSLiveAuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except KSLiveApiError as err:
            raise UpdateFailed(str(err)) from err
        return parse_catalog(payload, now=datetime.now(UTC))

    async def async_load_output(self) -> None:
        """Load the user's durable output choice."""
        stored = await self._output_store.async_load()
        if isinstance(stored, dict) and isinstance(stored.get("key"), str):
            self._selected_output_key = stored["key"]

    async def async_play(
        self,
        *,
        content_id: int | None = None,
        media_players: list[str] | None = None,
    ) -> None:
        """Resolve and play a live show or recording on configured players."""
        if content_id is None:
            content = self.data.playable if self.data else None
            if content is None:
                raise HomeAssistantError("No KSLive audio is currently available")
            content_id = content.content_id

        targets = tuple(dict.fromkeys(
            self.selected_targets if media_players is None else media_players
        ))
        if not targets:
            raise HomeAssistantError("No media players are configured for KSLive")
        key = (content_id, tuple(sorted(targets)))
        # Install the pending request before the first await. Every public Play
        # entry point joins the same request, including a slow token/API fetch.
        while self._play_task is not None:
            pending = self._play_task
            if self._pending_key == key:
                await asyncio.shield(pending)
                return
            with suppress(HomeAssistantError):
                await asyncio.shield(pending)
        if self._closing:
            raise HomeAssistantError("KSLive is unloading")
        self._pending_key = key
        task = self.hass.async_create_task(
            self._async_play_request(content_id, targets), "kslive-play"
        )
        self._play_task = task
        task.add_done_callback(self._play_finished)
        self.async_update_listeners()
        try:
            await asyncio.shield(task)
        finally:
            if task.done() and self._play_task is task:
                self._play_task = None
                self._pending_key = None
                self.async_update_listeners()

    @callback
    def _play_finished(self, task: asyncio.Task[None]) -> None:
        if self._play_task is task:
            self._play_task = None
            self._pending_key = None
            self.async_update_listeners()

    async def _async_play_request(self, content_id: int, targets: tuple[str, ...]) -> None:
        async with self._play_lock:
            if content_id == self.last_content_id and set(targets) == set(self.last_targets):
                self.output_state_changed()
                if all(target in self.active_targets for target in targets):
                    paused = [
                        target for target in targets
                        if (state := self.hass.states.get(target)) is not None
                        and state.state == "paused"
                        and owns_media_url(
                            self._sessions[target].media_url,
                            state.attributes.get("media_content_id"),
                        )
                    ]
                    if paused:
                        await self.hass.services.async_call(
                            MEDIA_PLAYER_DOMAIN, "media_play", {ATTR_ENTITY_ID: paused},
                            blocking=True,
                        )
                    if all(
                        target not in self._cleanup_tasks
                        or not self._sessions[target].established
                        or (
                            (state := self.hass.states.get(target)) is not None
                            and state.state == "buffering"
                        )
                        for target in targets
                    ):
                        return
        # A slow upstream request must not delay restoration when another app
        # takes over an existing output. Only speaker mutations hold the lock.
        try:
            stream_url = await self.client.async_playback_url(content_id)
        except KSLiveAuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except KSLivePlaybackError as err:
            raise HomeAssistantError(str(err)) from err
        except KSLiveApiError as err:
            raise HomeAssistantError("Unable to get the KSLive audio stream") from err

        async with self._play_lock:
            self.output_state_changed()
            # Output changes and service overrides share the same lifecycle.
            old_targets = tuple(self._sessions)
            stopped = [target for target in self.active_targets if target not in targets]
            if stopped:
                await self.hass.services.async_call(
                    MEDIA_PLAYER_DOMAIN, "media_stop", {ATTR_ENTITY_ID: stopped}, blocking=True
                )
            for target in old_targets:
                await self._async_release_target(target, self._sessions.get(target))
            self.last_content_id = content_id
            self.last_targets = targets
            entity_registry = er.async_get(self.hass)
            try:
                for target in targets:
                    registry_entry = entity_registry.async_get(target)
                    use_relay = needs_audio_relay(
                        registry_entry.platform if registry_entry is not None else None
                    )
                    media_url = stream_url
                    if use_relay:
                        relay_path = await self.audio_proxy.async_create_path(target, stream_url)
                        media_url = async_process_play_media_url(self.hass, relay_path)
                    self._sessions[target] = OutputSession(
                        media_url, time.monotonic() + PLAYBACK_START_GRACE
                    )
                    await self.equalizer.async_apply((target,))
                    self._sessions[target].deadline = time.monotonic() + PLAYBACK_START_GRACE
                    self._cancel_cleanup(target)
                    await self.hass.services.async_call(
                        MEDIA_PLAYER_DOMAIN,
                        SERVICE_PLAY_MEDIA,
                        {
                            ATTR_ENTITY_ID: target,
                            "media_content_id": media_url,
                            "media_content_type": "music",
                        },
                        blocking=True,
                    )
                    self.output_state_changed()
            except BaseException:
                for target in targets:
                    await self._async_release_target(target, self._sessions.get(target))
                raise
            self.async_update_listeners()

    async def async_stop_relays(self, targets: tuple[str, ...]) -> None:
        """Stop any audio-only relays assigned to the supplied players."""
        await asyncio.gather(
            *(self.audio_proxy.async_stop_target(target) for target in targets)
        )

    async def async_stop_playback_effects(self, targets: tuple[str, ...]) -> None:
        """Stop relays and restore speaker settings captured for KSLive."""
        await self._async_cancel_pending_play()
        async with self._play_lock:
            for target in targets:
                await self._async_release_target(target, self._sessions.get(target))
        self.async_update_listeners()

    async def _async_cancel_pending_play(self) -> None:
        task = self._play_task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError, HomeAssistantError):
                await task
            if self._play_task is task:
                self._play_task = None
                self._pending_key = None

    async def async_stop(self) -> None:
        """Cancel pending playback and stop only outputs still owned by KSLive."""
        await self._async_cancel_pending_play()
        targets = self.active_targets
        try:
            if targets:
                await self.hass.services.async_call(
                    MEDIA_PLAYER_DOMAIN, "media_stop", {ATTR_ENTITY_ID: list(targets)},
                    blocking=True,
                )
        finally:
            await self.async_stop_playback_effects(tuple(self._sessions))

    async def async_shutdown(self) -> None:
        """Restore every captured output, including explicit service overrides."""
        self._closing = True
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None
        await self.async_stop_playback_effects(tuple(self._sessions))
        await self.equalizer.async_restore_all()

    async def _async_release_target(
        self, target: str, session: OutputSession | None
    ) -> None:
        """Release one session while holding the playback lifecycle lock."""
        if session is not None and self._sessions.get(target) is not session:
            return
        self._sessions.pop(target, None)
        self._cancel_cleanup(target)
        await self.audio_proxy.async_stop_target(target)
        await self.equalizer.async_restore((target,))

    async def async_set_equalizer(self, key: str, value: float | bool) -> None:
        """Persist an EQ preset change and apply it to active KSLive outputs."""
        was_enabled = self.equalizer.settings.enabled
        await self.equalizer.async_set(key, value)
        async with self._play_lock:
            self.output_state_changed()
            if key == "enabled" and was_enabled and not bool(value):
                await self.equalizer.async_restore(self.active_targets)
            elif self.equalizer.settings.enabled:
                await self.equalizer.async_apply(self.active_targets)
        self.async_update_listeners()

    def output_state_changed(self) -> None:
        """Restore KSLive-only effects after an external stop or source change."""
        now = time.monotonic()
        for target, session in tuple(self._sessions.items()):
            state = self.hass.states.get(target)
            delay = session.observe(
                state.state if state is not None else "unknown",
                state.attributes.get("media_content_id") if state is not None else None,
                now,
            )
            if delay is None:
                self._cancel_cleanup(target)
            elif delay == 0 or target not in self._cleanup_tasks:
                self._cancel_cleanup(target)
                self._cleanup_tasks[target] = self.hass.async_create_task(
                    self._async_cleanup_target(target, session, delay), "kslive-output-release"
                )

    async def _async_cleanup_target(
        self, target: str, session: OutputSession, delay: float
    ) -> None:
        try:
            await asyncio.sleep(delay)
            async with self._play_lock:
                if self._sessions.get(target) is not session:
                    return
                state = self.hass.states.get(target)
                remaining = session.observe(
                    state.state if state is not None else "unknown",
                    state.attributes.get("media_content_id") if state is not None else None,
                    time.monotonic(),
                )
                if remaining is None:
                    return
                # A buffering event may have extended an earlier idle timer.
                if remaining > 0 and (
                    not session.established or (state is not None and state.state == "buffering")
                ):
                    self._cleanup_tasks.pop(target, None)
                    self.output_state_changed()
                    return
                await self._async_release_target(target, session)
            self.async_update_listeners()
        finally:
            if self._cleanup_tasks.get(target) is asyncio.current_task():
                self._cleanup_tasks.pop(target, None)

    def _cancel_cleanup(self, target: str) -> None:
        task = self._cleanup_tasks.pop(target, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    @property
    def playback_active(self) -> bool:
        return bool(self.active_targets) or self._pending_key is not None

    @property
    def active_targets(self) -> tuple[str, ...]:
        return tuple(target for target, session in self._sessions.items() if not session.released)

    @property
    def playback_starting(self) -> bool:
        """Return whether a selected output is inside its startup grace period."""
        return self._pending_key is not None or any(
            not session.established and not session.released
            for session in self._sessions.values()
        )

    @property
    def configured_players(self) -> tuple[str, ...]:
        """Return the output players selected in integration options."""
        return tuple(self.entry.options.get(CONF_MEDIA_PLAYERS, []))

    @property
    def output_sources(self) -> dict[str, tuple[str, ...]]:
        """Return display names mapped to one or more output entities."""
        players = self.configured_players
        sources: dict[str, tuple[str, ...]] = {}
        used_names: set[str] = {ALL_SPEAKERS_SOURCE}
        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        for entity_id in players:
            registry_entry = entity_registry.async_get(entity_id)
            device = (
                device_registry.async_get(registry_entry.device_id)
                if registry_entry is not None and registry_entry.device_id is not None
                else None
            )
            name = self._output_labels.get(entity_id) or first_output_name(
                (
                    registry_entry.name if registry_entry else None,
                    device.name_by_user if device else None,
                    device.name if device else None,
                    registry_entry.original_name if registry_entry else None,
                ),
                entity_id,
            )
            while name in used_names:
                name = f"{name} ({entity_id})"
            used_names.add(name)
            self._output_labels[entity_id] = name
            sources[name] = (entity_id,)
        if len(players) > 1:
            sources[ALL_SPEAKERS_SOURCE] = players
        return sources

    @property
    def selected_source(self) -> str | None:
        """Return the current output selection without starting playback."""
        sources = self.output_sources
        for source, targets in sources.items():
            if self._output_key(targets) == self._selected_output_key:
                return source
        if not sources:
            return None
        source, targets = next(iter(sources.items()))
        self._selected_output_key = self._output_key(targets)
        return source

    @property
    def selected_targets(self) -> tuple[str, ...]:
        """Return the entity IDs for the current output selection."""
        source = self.selected_source
        return self.output_sources.get(source, ()) if source is not None else ()

    async def async_select_source(self, source: str) -> None:
        """Select an output without transferring or starting playback."""
        targets = self.output_sources.get(source)
        if targets is None:
            raise HomeAssistantError(f"Unknown KSLive output: {source}")
        self._selected_output_key = self._output_key(targets)
        await self._output_store.async_save({"key": self._selected_output_key})
        self.async_update_listeners()

    def _output_key(self, targets: tuple[str, ...]) -> str:
        """Return a stable storage key independent of speaker display names."""
        if len(targets) == 1:
            return targets[0]
        return ALL_SPEAKERS_SOURCE

    def content(self, content_id: int | None = None):
        """Return a catalog item by ID, or the current queue item."""
        if self.data is None:
            return None
        wanted = content_id if content_id is not None else self.last_content_id
        if wanted is not None:
            return next(
                (item for item in self.data.playable_items if item.content_id == wanted),
                None,
            )
        return self.data.playable

    def adjacent_content(self, step: int):
        """Return the previous or next playable catalog item, wrapping at the ends."""
        if self.data is None or not self.data.playable_items:
            return None
        items = self.data.playable_items
        current_id = self.last_content_id
        index = next(
            (position for position, item in enumerate(items) if item.content_id == current_id),
            -1 if step > 0 else 0,
        )
        return items[(index + step) % len(items)]
