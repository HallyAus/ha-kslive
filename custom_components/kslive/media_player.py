"""Spotify-style media player for KSLive audio."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaPlayerDeviceClass,
    MediaPlayerEnqueue,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import MEDIA_ID_PREFIX
from .coordinator import KSLiveCoordinator
from .entity import KSLiveEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the KSLive media player."""
    coordinator: KSLiveCoordinator = hass.data["kslive"][entry.entry_id]
    async_add_entities([KSLiveMediaPlayer(coordinator)])


class KSLiveMediaPlayer(KSLiveEntity, MediaPlayerEntity):
    """Browse KSLive and route playback to a selected speaker output."""

    _attr_name = "Player"
    _attr_icon = "mdi:radio"
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_media_image_remotely_accessible = True

    def __init__(self, coordinator: KSLiveCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_player"

    async def async_added_to_hass(self) -> None:
        """Track output state changes so the proxy controls stay current."""
        await super().async_added_to_hass()
        if self.coordinator.configured_players:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    self.coordinator.configured_players,
                    self._async_output_state_changed,
                )
            )

    @callback
    def _async_output_state_changed(self, _event: Event) -> None:
        self.coordinator.output_state_changed()
        self.async_write_ha_state()

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Return the controls offered by the KSLive player."""
        return (
            MediaPlayerEntityFeature.BROWSE_MEDIA
            | MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PLAY_MEDIA
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
            | MediaPlayerEntityFeature.SELECT_SOURCE
            | MediaPlayerEntityFeature.STOP
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.VOLUME_SET
        )

    @property
    def state(self) -> MediaPlayerState:
        """Mirror KSLive playback on the selected output."""
        if not self.coordinator.playback_active:
            return MediaPlayerState.IDLE
        states = [
            self.hass.states.get(entity_id)
            for entity_id in (self.coordinator.last_targets or self._targets)
        ]
        raw_states = {state.state for state in states if state is not None}
        if "playing" in raw_states:
            return MediaPlayerState.PLAYING
        if "paused" in raw_states:
            return MediaPlayerState.PAUSED
        if self.coordinator.playback_starting or "buffering" in raw_states:
            return MediaPlayerState.BUFFERING
        if raw_states and raw_states <= {"off", "unavailable", "unknown"}:
            return MediaPlayerState.OFF
        return MediaPlayerState.IDLE

    @property
    def source_list(self) -> list[str]:
        """Return individual speakers and the multi-speaker output."""
        return list(self.coordinator.output_sources)

    @property
    def source(self) -> str | None:
        return self.coordinator.selected_source

    @property
    def _targets(self) -> tuple[str, ...]:
        return self.coordinator.selected_targets

    @property
    def _active_targets(self) -> tuple[str, ...]:
        if self.coordinator.playback_active and self.coordinator.last_targets:
            return self.coordinator.last_targets
        return self._targets

    @property
    def _content(self):
        return self.coordinator.content()

    @property
    def media_content_id(self) -> str | None:
        content = self._content
        return f"{MEDIA_ID_PREFIX}{content.content_id}" if content else None

    @property
    def media_content_type(self) -> str:
        return MediaType.MUSIC

    @property
    def media_title(self) -> str | None:
        content = self._content
        return content.title if content else None

    @property
    def media_artist(self) -> str:
        return "KSLive"

    @property
    def media_album_name(self) -> str:
        return "Subscriber audio"

    @property
    def media_image_url(self) -> str | None:
        content = self._content
        return content.image_url if content else None

    @property
    def volume_level(self) -> float | None:
        state = self.hass.states.get(self._targets[0]) if self._targets else None
        value = state.attributes.get("volume_level") if state else None
        return float(value) if isinstance(value, int | float) else None

    @property
    def is_volume_muted(self) -> bool | None:
        state = self.hass.states.get(self._targets[0]) if self._targets else None
        value = state.attributes.get("is_volume_muted") if state else None
        return value if isinstance(value, bool) else None

    async def async_select_source(self, source: str) -> None:
        """Choose an output without starting playback."""
        self.coordinator.select_source(source)

    async def async_play_media(
        self,
        media_type: str,
        media_id: str,
        enqueue: MediaPlayerEnqueue | None = None,
        announce: bool | None = None,
        **kwargs: Any,
    ) -> None:
        """Play a catalog item selected in Home Assistant's media browser."""
        del media_type, enqueue, announce, kwargs
        value = media_id.removeprefix(MEDIA_ID_PREFIX)
        try:
            content_id = int(value)
        except ValueError as err:
            raise ValueError(f"Invalid KSLive media ID: {media_id}") from err
        await self._async_prepare_selected_output()
        await self.coordinator.async_play(
            content_id=content_id,
            media_players=list(self._targets),
        )

    async def async_media_play(self) -> None:
        """Resume a paused output or start the selected KSLive item."""
        states = [self.hass.states.get(entity_id) for entity_id in self._targets]
        if self.coordinator.playback_active and any(
            state is not None and state.state == "paused" for state in states
        ) and self.coordinator.last_targets == self._targets:
            await self._call_output("media_play", targets=self._active_targets)
            return
        await self._async_prepare_selected_output()
        content = self._content
        await self.coordinator.async_play(
            content_id=content.content_id if content else None,
            media_players=list(self._targets),
        )

    async def async_media_pause(self) -> None:
        await self._call_output("media_pause", targets=self._active_targets)

    async def async_media_stop(self) -> None:
        await self._call_output("media_stop", targets=self._active_targets)
        await self.coordinator.async_stop_playback_effects(self._active_targets)
        self.coordinator.playback_active = False
        self.coordinator.async_set_updated_data(self.coordinator.data)

    async def async_media_next_track(self) -> None:
        content = self.coordinator.adjacent_content(1)
        if content is not None:
            await self._async_prepare_selected_output()
            await self.coordinator.async_play(
                content_id=content.content_id,
                media_players=list(self._targets),
            )

    async def async_media_previous_track(self) -> None:
        content = self.coordinator.adjacent_content(-1)
        if content is not None:
            await self._async_prepare_selected_output()
            await self.coordinator.async_play(
                content_id=content.content_id,
                media_players=list(self._targets),
            )

    async def async_set_volume_level(self, volume: float) -> None:
        await self._call_output("volume_set", {"volume_level": volume})

    async def async_mute_volume(self, mute: bool) -> None:
        await self._call_output("volume_mute", {"is_volume_muted": mute})

    async def _call_output(
        self,
        service: str,
        data: dict[str, Any] | None = None,
        *,
        targets: tuple[str, ...] | None = None,
    ) -> None:
        """Send a media-player control to the selected output entities."""
        selected = targets if targets is not None else self._targets
        if not selected:
            raise HomeAssistantError("No media players are configured for KSLive")
        payload: dict[str, Any] = {ATTR_ENTITY_ID: list(selected)}
        payload.update(data or {})
        await self.hass.services.async_call(
            "media_player", service, payload, blocking=True
        )

    async def _async_prepare_selected_output(self) -> None:
        """Stop an old output before intentionally starting on a newly selected one."""
        if (
            self.coordinator.playback_active
            and self.coordinator.last_targets
            and self.coordinator.last_targets != self._targets
        ):
            await self._call_output(
                "media_stop", targets=self.coordinator.last_targets
            )
            await self.coordinator.async_stop_playback_effects(
                self.coordinator.last_targets
            )
            self.coordinator.playback_active = False

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Expose the KSLive catalogue in Home Assistant's media browser."""
        del media_content_type, media_content_id
        items = self.coordinator.data.playable_items if self.coordinator.data else ()
        children = [
            BrowseMedia(
                media_content_id=f"{MEDIA_ID_PREFIX}{item.content_id}",
                media_class=MediaClass.MUSIC,
                media_content_type=MediaType.MUSIC,
                title=item.title,
                can_expand=False,
                can_play=True,
                thumbnail=item.image_url,
            )
            for item in items
        ]
        return BrowseMedia(
            media_content_id="kslive",
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.MUSIC,
            title="KSLive Audio",
            can_expand=True,
            can_play=False,
            children=children,
            children_media_class=MediaClass.MUSIC,
        )
