"""KSLive data coordinator and playback orchestration."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.components.media_player.const import SERVICE_PLAY_MEDIA
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import KSLiveApiClient, KSLiveApiError, KSLiveAuthenticationError, KSLivePlaybackError
from .const import (
    CONF_MEDIA_PLAYERS,
    CONF_SEARCH_QUERY,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SEARCH_QUERY,
    NAME,
)
from .models import KSLiveCatalog, parse_catalog


class KSLiveCoordinator(DataUpdateCoordinator[KSLiveCatalog]):
    """Fetch catalog updates and send audio to Home Assistant players."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: KSLiveApiClient
    ) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=NAME,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.entry = entry
        self.client = client

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

        await self.hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_PLAY_MEDIA,
            {
                ATTR_ENTITY_ID: targets,
                "media_content_id": stream_url,
                "media_content_type": "music",
            },
            blocking=True,
        )

