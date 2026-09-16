"""Diagnostics support for KSLive."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL
from homeassistant.core import HomeAssistant

from .const import CONF_ACCESS_TOKEN, CONF_DEVICE_ID, CONF_REFRESH_TOKEN, DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    """Return diagnostics with all account secrets removed."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    safe_data = {
        key: "**REDACTED**"
        if key in {CONF_EMAIL, CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN, CONF_DEVICE_ID}
        else value
        for key, value in entry.data.items()
    }
    catalog = coordinator.data
    return {
        "entry": {"data": safe_data, "options": dict(entry.options)},
        "catalog": {
            "state": catalog.state,
            "content_ids": [item.content_id for item in catalog.items],
            "count": len(catalog.items),
        },
    }
