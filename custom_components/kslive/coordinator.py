"""KSLive data coordinator and playback orchestration."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.components.media_player import async_process_play_media_url
from homeassistant.components.media_player.const import SERVICE_PLAY_MEDIA
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import entity_registry as er
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
from .playback_state import ACTIVE_OUTPUT_STATES, PLAYBACK_START_GRACE, inactive_cleanup_delay
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
        self.playback_active = False
        self._selected_source: str | None = None
        self._inactive_cleanup_task: asyncio.Task[None] | None = None
        self._playback_start_deadline: float | None = None

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

        targets = media_players or list(self.entry.options.get(CONF_MEDIA_PLAYERS, []))
        if not targets:
            raise HomeAssistantError("No media players are configured for KSLive")

        try:
            stream_url = await self.client.async_playback_url(content_id)
        except KSLiveAuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except KSLivePlaybackError as err:
            raise HomeAssistantError(str(err)) from err
        except KSLiveApiError as err:
            raise HomeAssistantError("Unable to get the KSLive audio stream") from err

        self._cancel_inactive_cleanup()
        target_tuple = tuple(targets)
        self.last_content_id = content_id
        self.last_targets = target_tuple
        self.playback_active = True
        self._playback_start_deadline = time.monotonic() + PLAYBACK_START_GRACE
        await self.equalizer.async_apply(target_tuple)
        try:
            entity_registry = er.async_get(self.hass)
            for target in targets:
                registry_entry = entity_registry.async_get(target)
                use_relay = needs_audio_relay(
                    registry_entry.platform if registry_entry is not None else None
                )
                media_url = stream_url
                if use_relay:
                    relay_path = await self.audio_proxy.async_create_path(target, stream_url)
                    media_url = async_process_play_media_url(self.hass, relay_path)

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
        except Exception:
            await self.async_stop_playback_effects(target_tuple)
            self.playback_active = False
            raise

        self.async_set_updated_data(self.data)
        self.output_state_changed()

    async def async_stop_relays(self, targets: tuple[str, ...]) -> None:
        """Stop any audio-only relays assigned to the supplied players."""
        await asyncio.gather(
            *(self.audio_proxy.async_stop_target(target) for target in targets)
        )

    async def async_stop_playback_effects(self, targets: tuple[str, ...]) -> None:
        """Stop relays and restore speaker settings captured for KSLive."""
        self._cancel_inactive_cleanup()
        self._playback_start_deadline = None
        await self.async_stop_relays(targets)
        await self.equalizer.async_restore(targets)

    async def async_set_equalizer(self, key: str, value: float | bool) -> None:
        """Persist an EQ preset change and apply it to active KSLive outputs."""
        was_enabled = self.equalizer.settings.enabled
        await self.equalizer.async_set(key, value)
        if not self.playback_active or not self.last_targets:
            self.async_set_updated_data(self.data)
            return
        if key == "enabled" and was_enabled and not bool(value):
            await self.equalizer.async_restore(self.last_targets)
        elif self.equalizer.settings.enabled:
            await self.equalizer.async_apply(self.last_targets)
        self.async_set_updated_data(self.data)

    def output_state_changed(self) -> None:
        """Restore KSLive-only effects after an external stop or source change."""
        if not self.playback_active or not self.last_targets:
            return
        active_states = {
            state.state
            for target in self.last_targets
            if (state := self.hass.states.get(target)) is not None
        }
        if active_states & ACTIVE_OUTPUT_STATES:
            self._playback_start_deadline = None
            self._cancel_inactive_cleanup()
            return
        startup_remaining = max(
            0.0, (self._playback_start_deadline or 0.0) - time.monotonic()
        )
        delay = inactive_cleanup_delay(active_states, startup_remaining)
        if delay is not None:
            self._schedule_inactive_cleanup(delay)

    def _schedule_inactive_cleanup(self, delay: float) -> None:
        """Schedule one cleanup without shortening an existing start-up grace."""
        if self._inactive_cleanup_task is not None:
            return
        self._inactive_cleanup_task = self.hass.async_create_task(
            self._async_cleanup_if_inactive(delay),
            "kslive-equalizer-restore",
        )

    async def _async_cleanup_if_inactive(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            if any(
                (state := self.hass.states.get(target)) is not None
                and state.state in ACTIVE_OUTPUT_STATES
                for target in self.last_targets
            ):
                self._playback_start_deadline = None
                return
            self._playback_start_deadline = None
            await self.async_stop_playback_effects(self.last_targets)
            self.playback_active = False
            self.async_set_updated_data(self.data)
        finally:
            self._inactive_cleanup_task = None

    def _cancel_inactive_cleanup(self) -> None:
        task = self._inactive_cleanup_task
        self._inactive_cleanup_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    @property
    def playback_starting(self) -> bool:
        """Return whether a selected output is inside its startup grace period."""
        return bool(
            self._playback_start_deadline is not None
            and self._playback_start_deadline > time.monotonic()
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
        used_names: set[str] = set()
        for entity_id in players:
            state = self.hass.states.get(entity_id)
            name = (
                str(state.attributes.get("friendly_name"))
                if state and state.attributes.get("friendly_name")
                else entity_id
            )
            if name in used_names:
                name = f"{name} ({entity_id})"
            used_names.add(name)
            sources[name] = (entity_id,)
        if len(players) > 1:
            sources[ALL_SPEAKERS_SOURCE] = players
        return sources

    @property
    def selected_source(self) -> str | None:
        """Return the current output selection without starting playback."""
        sources = self.output_sources
        if self._selected_source not in sources:
            self._selected_source = next(iter(sources), None)
        return self._selected_source

    @property
    def selected_targets(self) -> tuple[str, ...]:
        """Return the entity IDs for the current output selection."""
        source = self.selected_source
        return self.output_sources.get(source, ()) if source is not None else ()

    def select_source(self, source: str) -> None:
        """Select an output without transferring or starting playback."""
        if source not in self.output_sources:
            raise HomeAssistantError(f"Unknown KSLive output: {source}")
        self._selected_source = source
        self.async_set_updated_data(self.data)

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
