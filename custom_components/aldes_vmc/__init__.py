"""Aldes VMC (locale): integrazione non ufficiale per la VMC Aldes InspirAIR Home S.

Progetto indipendente da Aldes. Usa l'app "Aldes Bridge" di saniho (MIT) via HTTP.
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import AldesBridgeClient, AldesBridgeError
from .const import CONF_HOST, CONF_PORT, DOMAIN, SERVICE_SEND_COMMAND
from .coordinator import AldesCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor", "select", "button"]

type AldesConfigEntry = ConfigEntry[AldesCoordinator]

SEND_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required("method"): cv.string,
        vol.Optional("params", default=[]): vol.All(cv.ensure_list, list),
        vol.Optional("config_entry_id"): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registra il servizio avanzato."""

    async def _send_command(call: ServiceCall) -> None:
        entries = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.state is ConfigEntryState.LOADED
        ]
        wanted = call.data.get("config_entry_id")
        if wanted:
            entries = [e for e in entries if e.entry_id == wanted]
        if not entries:
            raise ServiceValidationError("Nessuna VMC Aldes configurata e attiva")
        coordinator: AldesCoordinator = entries[0].runtime_data
        try:
            await coordinator.async_send_raw(call.data["method"], call.data["params"])
        except AldesBridgeError as err:
            raise HomeAssistantError(f"Invio fallito: {err}") from err

    hass.services.async_register(
        DOMAIN, SERVICE_SEND_COMMAND, _send_command, schema=SEND_COMMAND_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AldesConfigEntry) -> bool:
    """Configura la VMC."""
    client = AldesBridgeClient(
        async_get_clientsession(hass), entry.data[CONF_HOST], entry.data[CONF_PORT]
    )
    coordinator = AldesCoordinator(hass, entry, client, entry.unique_id or "")
    await coordinator.async_config_entry_first_refresh()
    await coordinator.boost.async_load()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: AldesConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AldesConfigEntry) -> bool:
    """Scarica la VMC (il Boost salvato resta e riparte al prossimo avvio)."""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        entry.runtime_data.boost.async_unload()
        entry.runtime_data.async_shutdown_followups()
    return ok


async def async_remove_entry(hass: HomeAssistant, entry: AldesConfigEntry) -> None:
    """Cancella il file del Boost salvato."""
    from homeassistant.helpers.storage import Store

    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()
