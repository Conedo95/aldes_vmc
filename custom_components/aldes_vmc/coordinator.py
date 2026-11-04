"""Coordinatore dei dati e invio comandi per Aldes VMC (locale)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AldesBridgeClient, AldesBridgeError, BridgeState
from .level_timer import LevelTimer
from .filters import FilterTracker
from .const import (
    COMMAND_MIN_INTERVAL,
    COMMAND_VERIFY_TIMEOUT,
    CONF_BOOST_MINUTES,
    CONF_KITCHEN_MINUTES,
    CONF_SCAN_INTERVAL,
    CONF_VACATION_DAYS,
    DEFAULT_BOOST_MINUTES,
    DEFAULT_KITCHEN_MINUTES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_VACATION_DAYS,
    DOMAIN,
    MODE_BOOST,
    MODE_KITCHEN,
    MODE_VACATION,
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
        # Cucina usa il vecchio file del Boost (stesso nome): il timer salvato si migra da solo
        self.kitchen = LevelTimer(
            hass, entry, self, name="Cucina", code=MODE_KITCHEN,
            option_key=CONF_KITCHEN_MINUTES, default_minutes=DEFAULT_KITCHEN_MINUTES,
        )
        self.boost = LevelTimer(
            hass, entry, self, name="Boost", code=MODE_BOOST,
            option_key=CONF_BOOST_MINUTES, default_minutes=DEFAULT_BOOST_MINUTES,
            store_suffix=".boost",
        )
        self.timers = (self.kitchen, self.boost)
        self.filters = FilterTracker(hass, entry, self)
        self._last_state: BridgeState | None = None
        # Modalita' richiesta in attesa di conferma dalla Box
        self.pending_code: str | None = None
        self._pending_since: float = 0.0
        self._followups: list = []
        # Affidabilita' dei comandi
        self._send_lock = asyncio.Lock()
        self._last_send: float | None = None
        self._verify_task: asyncio.Task | None = None
        self.last_command_error: str | None = None

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
        for timer in self.timers:
            await timer.async_data_updated(data)
        await self.filters.async_data_updated(data)
        return data

    def _update_pending(self, data: AldesData) -> None:
        if self.pending_code is None:
            return
        if data.mode_code == self.pending_code and data.data_ts >= self._pending_since:
            self.pending_code = None
        elif time.time() - self._pending_since > PENDING_TIMEOUT:
            self.pending_code = None

    async def async_cancel_timers(self, keep: LevelTimer | None = None) -> None:
        for timer in self.timers:
            if timer is not keep:
                await timer.async_cancel()

    async def async_send_vacation(self) -> None:
        """Vacanza: changeMode con UNA stringa "W" + inizio + fine (UTC, YYYYMMDDHHMMSSZ).

        La data di fine e' solo di sicurezza: la Vacanza non ha un timer di rientro.
        """
        days = self.config_entry.options.get(CONF_VACATION_DAYS, DEFAULT_VACATION_DAYS)
        start = dt_util.utcnow().replace(microsecond=0)
        end = start + timedelta(days=days)
        fmt = "%Y%m%d%H%M%S"
        param = f"{MODE_VACATION}{start.strftime(fmt)}Z{end.strftime(fmt)}Z"
        await self.async_send_mode(MODE_VACATION, [param])

    async def _async_send(self, method: str, params: list[Any]) -> float:
        """Invia rispettando la pausa minima (i comandi ravvicinati aspettano, non si perdono).

        Restituisce l'istante dell'invio."""
        async with self._send_lock:
            if self._last_send is not None:
                wait = COMMAND_MIN_INTERVAL - (time.monotonic() - self._last_send)
                if wait > 0:
                    _LOGGER.debug("Comando in attesa %.0f s (pausa minima)", wait)
                    await asyncio.sleep(wait)
            sent_at = time.time()
            await self.client.send_command(self.client_id, method, params)
            self._last_send = time.monotonic()
            return sent_at

    async def async_send_mode(self, code: str, params: list[str] | None = None) -> None:
        """Invia changeMode, poi verifica che la Box lo esegua (un solo nuovo invio)."""
        params = params or [code]
        previous = self.data.mode_code if self.data else None
        sent_at = await self._async_send("changeMode", params)
        self.pending_code = code
        self._pending_since = sent_at
        self.async_update_listeners()
        self._schedule_followups()
        self._cancel_verification()
        if previous != code:  # se era gia' in quella modalita' non c'e' nulla da verificare
            self._verify_task = self.config_entry.async_create_background_task(
                self.hass, self._async_verify(code, params, sent_at), "aldes_vmc verifica comando"
            )

    def _cancel_verification(self) -> None:
        if self._verify_task and not self._verify_task.done():
            self._verify_task.cancel()
        self._verify_task = None

    async def _async_verify(self, code: str, params: list[str], sent_at: float) -> None:
        """Entro COMMAND_VERIFY_TIMEOUT la Box deve riportare la modalita'; se no, un nuovo invio."""
        for attempt in (1, 2):
            await asyncio.sleep(COMMAND_VERIFY_TIMEOUT)
            await self.async_refresh()
            d = self.data
            if d is not None and d.mode_code == code and d.data_ts >= sent_at - 2:
                self.last_command_error = None
                self.async_update_listeners()
                return
            if attempt == 1:
                _LOGGER.info(
                    "La Box non ha confermato la modalita' %s entro %s s: nuovo invio",
                    code, COMMAND_VERIFY_TIMEOUT,
                )
                try:
                    sent_at = await self._async_send("changeMode", params)
                except AldesBridgeError as err:
                    _LOGGER.warning("Nuovo invio della modalita' %s fallito: %s", code, err)
                    break
                self._pending_since = sent_at
        self.last_command_error = (
            f"{dt_util.now().isoformat(timespec='seconds')}: modalita' {code} non confermata dalla Box"
        )
        _LOGGER.warning(
            "Modalita' %s non confermata dalla Box dopo due invii: nessun altro tentativo", code
        )
        self.pending_code = None
        self.async_update_listeners()

    async def async_send_raw(self, method: str, params: list[Any]) -> None:
        await self._async_send(method, params)
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
        self._cancel_verification()
        for unsub in self._followups:
            unsub()
        self._followups = []
