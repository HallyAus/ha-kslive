"""Config flow for KSLive."""

from __future__ import annotations

import uuid
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import KSLiveApiClient, KSLiveApiError, KSLiveAuthenticationError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_ID,
    CONF_IDLE_SLEEP,
    CONF_MEDIA_PLAYERS,
    CONF_REFRESH_TOKEN,
    CONF_SEARCH_QUERY,
    CONF_TOKEN_EXPIRES_AT,
    DEFAULT_SEARCH_QUERY,
    DOMAIN,
    NAME,
)


def _login_schema(default_email: str = "") -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_EMAIL, default=default_email): str,
            vol.Required(CONF_PASSWORD): str,
        }
    )


class KSLiveConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure a KSLive subscriber account."""

    VERSION = 1
    _pending_data: dict[str, Any]
    _device_id: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip().lower()
            # Reject duplicates before the login request can register a device.
            await self.async_set_unique_id(email)
            self._abort_if_unique_id_configured()
            if self._device_id is None:
                self._device_id = str(uuid.uuid4())
            device_id = self._device_id
            client = KSLiveApiClient(
                async_get_clientsession(self.hass), device_id=device_id
            )
            try:
                login = await client.async_login(email, user_input[CONF_PASSWORD])
            except KSLiveAuthenticationError:
                errors["base"] = "invalid_auth"
            except KSLiveApiError:
                errors["base"] = "cannot_connect"
            else:
                user = login.get("user") if isinstance(login.get("user"), dict) else {}
                if user.get("subscribed") is False:
                    errors["base"] = "subscription_required"
                else:
                    auth = client.auth_data
                    self._pending_data = {
                        CONF_EMAIL: email,
                        CONF_ACCESS_TOKEN: auth[CONF_ACCESS_TOKEN],
                        CONF_REFRESH_TOKEN: auth[CONF_REFRESH_TOKEN],
                        CONF_TOKEN_EXPIRES_AT: auth[CONF_TOKEN_EXPIRES_AT],
                        CONF_DEVICE_ID: device_id,
                    }
                    return await self.async_step_speakers()
        return self.async_show_form(step_id="user", data_schema=_login_schema(), errors=errors)

    async def async_step_speakers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the speakers that receive KSLive audio."""
        if user_input is not None:
            return self.async_create_entry(
                title=NAME,
                data=self._pending_data,
                options={
                    CONF_MEDIA_PLAYERS: user_input.get(CONF_MEDIA_PLAYERS, []),
                    CONF_SEARCH_QUERY: DEFAULT_SEARCH_QUERY,
                    CONF_IDLE_SLEEP: True,
                },
            )
        return self.async_show_form(
            step_id="speakers",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_MEDIA_PLAYERS, default=[]): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="media_player", multiple=True)
                    )
                }
            ),
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None
        email = self._reauth_entry.data[CONF_EMAIL]
        if user_input is not None:
            client = KSLiveApiClient(
                async_get_clientsession(self.hass),
                device_id=self._reauth_entry.data.get(CONF_DEVICE_ID),
            )
            try:
                await client.async_login(email, user_input[CONF_PASSWORD])
            except KSLiveAuthenticationError:
                errors["base"] = "invalid_auth"
            except KSLiveApiError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    self._reauth_entry,
                    data_updates=client.auth_data,
                )
        schema = vol.Schema({vol.Required(CONF_PASSWORD): str})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={"email": email},
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return KSLiveOptionsFlow(config_entry)


class KSLiveOptionsFlow(OptionsFlow):
    """Configure target speakers and catalog matching."""

    def __init__(self, config_entry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_IDLE_SLEEP,
                        default=self._entry.options.get(CONF_IDLE_SLEEP, True),
                    ): bool,
                    vol.Optional(
                        CONF_MEDIA_PLAYERS,
                        default=self._entry.options.get(CONF_MEDIA_PLAYERS, []),
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="media_player", multiple=True)
                    ),
                    vol.Required(
                        CONF_SEARCH_QUERY,
                        default=self._entry.options.get(
                            CONF_SEARCH_QUERY, DEFAULT_SEARCH_QUERY
                        ),
                    ): str,
                }
            ),
        )
