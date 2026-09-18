"""KSLive integration."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import KSLiveApiClient
from .audio_proxy import DATA_AUDIO_PROXY, KSLiveAudioProxy, KSLiveAudioView
from .const import (
    ATTR_CONTENT_ID,
    ATTR_MEDIA_PLAYERS,
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_ID,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    DOMAIN,
    PLATFORMS,
    SERVICE_PLAY,
)
from .coordinator import KSLiveCoordinator
from .equalizer import KSLiveEqualizer

SERVICE_PLAY_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONTENT_ID): vol.Coerce(int),
        vol.Optional(ATTR_MEDIA_PLAYERS): cv.entity_ids,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up KSLive from a config entry."""

    async def async_tokens_updated(tokens: dict) -> None:
        hass.config_entries.async_update_entry(entry, data={**entry.data, **tokens})

    client = KSLiveApiClient(
        async_get_clientsession(hass),
        access_token=entry.data[CONF_ACCESS_TOKEN],
        refresh_token=entry.data[CONF_REFRESH_TOKEN],
        expires_at=entry.data.get(CONF_TOKEN_EXPIRES_AT),
        device_id=entry.data.get(CONF_DEVICE_ID),
        token_callback=async_tokens_updated,
    )
    audio_proxy = hass.data.get(DATA_AUDIO_PROXY)
    if audio_proxy is None:
        audio_proxy = KSLiveAudioProxy(hass, get_ffmpeg_manager(hass).binary)
        hass.data[DATA_AUDIO_PROXY] = audio_proxy
        hass.http.register_view(KSLiveAudioView(audio_proxy))

        async def async_stop_audio_proxy(_event) -> None:
            await audio_proxy.async_shutdown()

        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_stop_audio_proxy)

    equalizer = KSLiveEqualizer(hass, entry.entry_id)
    await equalizer.async_load()
    coordinator = KSLiveCoordinator(hass, entry, client, audio_proxy, equalizer)
    await coordinator.async_load_output()
    await coordinator.async_load_catalog()
    await coordinator.async_config_entry_first_refresh()

    async def async_restore_equalizer(_event) -> None:
        await coordinator.async_shutdown()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_restore_equalizer)
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    coordinator.start_tracking()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    if not hass.services.has_service(DOMAIN, SERVICE_PLAY):

        async def async_handle_play(call: ServiceCall) -> None:
            entries = hass.config_entries.async_entries(DOMAIN)
            if not entries:
                return
            selected: KSLiveCoordinator = hass.data[DOMAIN][entries[0].entry_id]
            await selected.async_play(
                content_id=call.data.get(ATTR_CONTENT_ID),
                media_players=call.data.get(ATTR_MEDIA_PLAYERS),
            )

        hass.services.async_register(
            DOMAIN, SERVICE_PLAY, async_handle_play, schema=SERVICE_PLAY_SCHEMA
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a KSLive config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    coordinator: KSLiveCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
    await coordinator.async_shutdown()
    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, SERVICE_PLAY)
        hass.data.pop(DOMAIN, None)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # Persisting a rotated login token also invokes this listener. Reloading in
    # that case would cancel the very Play request that woke the expired login.
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is not None and coordinator.loaded_options != dict(entry.options):
        await hass.config_entries.async_reload(entry.entry_id)
