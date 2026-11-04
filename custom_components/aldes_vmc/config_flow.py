"""Config flow e opzioni per Aldes VMC (locale)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    AldesBridgeClient,
    AldesBridgeConnectionError,
    AldesBridgeError,
)
from .const import (
    CONF_BOOST_MINUTES,
    CONF_FILTER_MONTHS,
    CONF_KITCHEN_MINUTES,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_STALE_MINUTES,
    CONF_VACATION_DAYS,
    DEFAULT_BOOST_MINUTES,
    DEFAULT_FILTER_MONTHS,
    DEFAULT_KITCHEN_MINUTES,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STALE_MINUTES,
    DEFAULT_VACATION_DAYS,
    DOMAIN,
    MAX_BOOST_MINUTES,
    MAX_FILTER_MONTHS,
    MAX_KITCHEN_MINUTES,
    MAX_SCAN_INTERVAL,
    MAX_VACATION_DAYS,
    MIN_BOOST_MINUTES,
    MIN_FILTER_MONTHS,
    MIN_KITCHEN_MINUTES,
    MIN_SCAN_INTERVAL,
    MIN_VACATION_DAYS,
)


class AldesVmcConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configurazione iniziale."""

    VERSION = 2
    MINOR_VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return AldesVmcOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = AldesBridgeClient(
                async_get_clientsession(self.hass),
                user_input[CONF_HOST],
                user_input[CONF_PORT],
            )
            try:
                await client.get_health()
                config = await client.get_config()
            except AldesBridgeConnectionError:
                errors["base"] = "cannot_connect"
            except AldesBridgeError:
                errors["base"] = "invalid_response"
            else:
                await self.async_set_unique_id(config["client_id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Aldes VMC (locale)", data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST,
                        default=(user_input or {}).get(CONF_HOST, DEFAULT_HOST),
                    ): str,
                    vol.Required(
                        CONF_PORT,
                        default=(user_input or {}).get(CONF_PORT, DEFAULT_PORT),
                    ): vol.All(int, vol.Range(min=1, max=65535)),
                }
            ),
            errors=errors,
        )


class AldesVmcOptionsFlow(OptionsFlow):
    """Opzioni: intervallo, durate Cucina e Boost, tolleranza dati obsoleti."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=o.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(
                        int, vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                    ),
                    vol.Required(
                        CONF_KITCHEN_MINUTES,
                        default=o.get(CONF_KITCHEN_MINUTES, DEFAULT_KITCHEN_MINUTES),
                    ): vol.All(
                        int, vol.Range(min=MIN_KITCHEN_MINUTES, max=MAX_KITCHEN_MINUTES)
                    ),
                    vol.Required(
                        CONF_BOOST_MINUTES,
                        default=o.get(CONF_BOOST_MINUTES, DEFAULT_BOOST_MINUTES),
                    ): vol.All(
                        int, vol.Range(min=MIN_BOOST_MINUTES, max=MAX_BOOST_MINUTES)
                    ),
                    vol.Required(
                        CONF_VACATION_DAYS,
                        default=o.get(CONF_VACATION_DAYS, DEFAULT_VACATION_DAYS),
                    ): vol.All(
                        int, vol.Range(min=MIN_VACATION_DAYS, max=MAX_VACATION_DAYS)
                    ),
                    vol.Required(
                        CONF_FILTER_MONTHS,
                        default=o.get(CONF_FILTER_MONTHS, DEFAULT_FILTER_MONTHS),
                    ): vol.All(
                        int, vol.Range(min=MIN_FILTER_MONTHS, max=MAX_FILTER_MONTHS)
                    ),
                    vol.Required(
                        CONF_STALE_MINUTES,
                        default=o.get(CONF_STALE_MINUTES, DEFAULT_STALE_MINUTES),
                    ): vol.All(int, vol.Range(min=10, max=240)),
                }
            ),
        )
