"""Aldes VMC (locale): integrazione non ufficiale per la VMC Aldes InspirAIR Home S.

Progetto indipendente da Aldes. Usa l'app "Aldes Bridge" di saniho (MIT) via HTTP.
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import AldesBridgeClient, AldesBridgeError
from .errors import command_error
from .const import (
    CONF_BOOST_MINUTES,
    CONF_HOST,
    CONF_KITCHEN_MINUTES,
    CONF_PORT,
    DEFAULT_BOOST_MINUTES,
    DEFAULT_KITCHEN_MINUTES,
    DOMAIN,
    SERVICE_SEND_COMMAND,
)
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
            raise command_error(err) from err

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
    await coordinator.filters.async_load()
    await coordinator.async_config_entry_first_refresh()
    for timer in coordinator.timers:
        await timer.async_load()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


def _async_rename_end_sensor(hass: HomeAssistant, entry: AldesConfigEntry) -> None:
    """Il sensore "Fine Boost" della 0.1.0 (Y) diventa "Fine Cucina": stessa entita' e stessa cronologia.

    L'entity_id viene cambiato solo se e' ancora quello predefinito (non se l'utente l'ha
    personalizzato) e se quello nuovo e' libero; in ogni caso l'unique_id viene aggiornato,
    cosi' il sensore "Fine Boost" nuovo (livello 3) non si confonde con il vecchio.
    """
    cid = entry.unique_id
    if not cid:
        return
    registry = er.async_get(hass)
    old_id = registry.async_get_entity_id("sensor", DOMAIN, f"{cid}_fine_boost")
    if old_id is None or registry.async_get_entity_id("sensor", DOMAIN, f"{cid}_fine_cucina"):
        return
    new_id = "sensor.vmc_aldes_fine_cucina"
    kwargs: dict[str, str] = {"new_unique_id": f"{cid}_fine_cucina"}
    if old_id == "sensor.vmc_aldes_fine_boost" and registry.async_get(new_id) is None:
        kwargs["new_entity_id"] = new_id
    try:
        registry.async_update_entity(old_id, **kwargs)
    except ValueError as err:
        _LOGGER.warning("Rinomina del sensore Fine Boost non riuscita: %s", err)


async def async_migrate_entry(hass: HomeAssistant, entry: AldesConfigEntry) -> bool:
    """v1 -> v2: il vecchio "Boost" (Y, 100 m3/h) diventa "Cucina"; il Boost e' il nuovo livello 3 (X)."""
    if entry.version == 1:  # (la migrazione prosegue sotto per minor_version)
        old = dict(entry.options)
        options = {k: v for k, v in old.items() if k != CONF_BOOST_MINUTES}
        options[CONF_KITCHEN_MINUTES] = old.get(CONF_BOOST_MINUTES, DEFAULT_KITCHEN_MINUTES)
        options[CONF_BOOST_MINUTES] = DEFAULT_BOOST_MINUTES
        hass.config_entries.async_update_entry(
            entry, options=options, version=2, minor_version=1
        )
        # il vecchio sensore "Fine Boost" diventa "Fine Cucina" (stessa entita', nuovo id)
        _async_rename_end_sensor(hass, entry)
    if entry.version == 2 and entry.minor_version < 2:
        # il Boost (livello 3) dura 60 minuti di default: correggo il valore provvisorio di 8 ore
        options = dict(entry.options)
        if options.get(CONF_BOOST_MINUTES) == 480:
            options[CONF_BOOST_MINUTES] = DEFAULT_BOOST_MINUTES
        hass.config_entries.async_update_entry(entry, options=options, minor_version=2)
    return True


async def _async_reload(hass: HomeAssistant, entry: AldesConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AldesConfigEntry) -> bool:
    """Scarica la VMC (i timer salvati restano e ripartono al prossimo avvio)."""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        for timer in entry.runtime_data.timers:
            timer.async_unload()
        entry.runtime_data.async_shutdown_followups()
    return ok


async def async_remove_entry(hass: HomeAssistant, entry: AldesConfigEntry) -> None:
    """Cancella i file salvati (timer e filtri)."""
    from homeassistant.helpers.storage import Store

    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.boost").async_remove()
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.filters").async_remove()
