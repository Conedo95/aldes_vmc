"""Coordinatore dei dati e invio comandi per Aldes VMC (locale)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AldesBridgeClient, AldesBridgeError, BridgeState
from .boost import BoostManager
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PENDING_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class AldesData:
    """Stato corrente della VMC."""

    payload: dict[str, Any]
    data_ts: float
    mode_code: str | None
    box_connected: bool
    mqtt_connected: bool
    bridge_uptime: float | None


class AldesCoordinator(DataUpdateCoordinator[AldesData]):
    """Legge il bridge e invia i comandi."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: AldesBridgeClient,
        client_id: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self.client_id = client_id
        self.boost = BoostManager(hass, entry, self)
        self._last_state: BridgeState | None = None
        # Modalita' richiesta in attesa di conferma dalla Box
        self.pending_code: str | None = None
        self._pending_since: float = 0.0
        self._followups: list = []

    async def _async_update_data(self) -> AldesData:
        try:
            health = await self.client.get_health()
        except AldesBridgeError as err:
            raise UpdateFailed(f"Bridge non raggiungibile: {err}") from err

        try:
            state = await self.client.get_latest_state()
        except AldesBridgeError as err:
            _LOGGER.debug("Stato non letto, uso l'ultimo noto: %s", err)
            state = None
        if state is not None:
            self._last_state = state
        elif self._last_state is None:
            raise UpdateFailed("Nessun dato dalla Box nello storico del bridge")
        state = self._last_state

        data = AldesData(
            payload=state.payload,
            data_ts=state.timestamp,
            mode_code=state.payload.get("current_mode") or None,
            box_connected=bool(health.get("box_connected")),
            mqtt_connected=bool(health.get("mqtt_connected")),
            bridge_uptime=health.get("uptime"),
        )
        self._update_pending(data)
        await self.boost.async_data_updated(data)
        return data

    def _update_pending(self, data: AldesData) -> None:
        if self.pending_code is None:
            return
        if data.mode_code == self.pending_code and data.data_ts >= self._pending_since:
            self.pending_code = None
        elif time.time() - self._pending_since > PENDING_TIMEOUT:
            self.pending_code = None

    async def async_send_mode(self, code: str) -> None:
        """Invia changeMode e programma letture di conferma ravvicinate."""
        await self.client.send_command(self.client_id, "changeMode", [code])
        self.pending_code = code
        self._pending_since = time.time()
        self.async_update_listeners()
        self._schedule_followups()

    async def async_send_raw(self, method: str, params: list[Any]) -> None:
        await self.client.send_command(self.client_id, method, params)
        self._schedule_followups()

    def _schedule_followups(self) -> None:
        for unsub in self._followups:
            unsub()
        self._followups = [
            async_call_later(self.hass, delay, self._followup) for delay in (15, 60)
        ]

    @callback
    def _followup(self, _now: Any) -> None:
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def async_shutdown_followups(self) -> None:
        for unsub in self._followups:
            unsub()
        self._followups = []
