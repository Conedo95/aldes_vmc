"""Coordinatore dei dati e invio comandi per Aldes VMC (locale)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AldesBoxNotConnectedError,
    AldesBridgeClient,
    AldesBridgeConnectionError,
    AldesBridgeError,
    BridgeState,
    CommandSuperseded,
)
from .connection import ConnectionMonitor
from .level_timer import LevelTimer
from .restore import RestoreManager
from .filters import FilterTracker
from .const import (
    BRIDGE_RETRY_SECONDS,
    BRIDGE_RETRY_WINDOW,
    COMMAND_MIN_INTERVAL,
    COMMAND_VERIFY_TIMEOUT,
    CONF_BOOST_MINUTES,
    CONF_KITCHEN_MINUTES,
    CONF_SCAN_INTERVAL,
    CONF_STALE_MINUTES,
    CONF_VACATION_DAYS,
    DEFAULT_BOOST_MINUTES,
    DEFAULT_KITCHEN_MINUTES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STALE_MINUTES,
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
        self._normal_interval = timedelta(
            seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=self._normal_interval,
        )
        self._failing_since: float | None = None
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
        self.monitor = ConnectionMonitor(hass, entry, self)
        self.restore = RestoreManager(hass, entry, self)
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
            self.monitor.update(False)
            await self.restore.async_process(self.data, False)
            self._set_retry_interval()
            raise UpdateFailed(f"Bridge non raggiungibile: {err}") from err

        try:
            state = await self.client.get_latest_state()
        except AldesBridgeError as err:
            _LOGGER.debug("Stato non letto, uso l'ultimo noto: %s", err)
            state = None
        if state is not None:
            self._last_state = state
        elif self._last_state is None:
            self._set_retry_interval()
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
        self._failing_since = None
        self.update_interval = self._normal_interval
        connected = data.box_connected and data.mqtt_connected
        self.monitor.update(connected, data.data_ts)
        await self.restore.async_process(data, connected)
        self._update_pending(data)
        for timer in self.timers:
            await timer.async_data_updated(data)
        await self.filters.async_data_updated(data)
        return data

    def _set_retry_interval(self) -> None:
        """Lettura fallita: riprova ogni 30 s per al massimo 10 minuti, poi ciclo normale."""
        now = time.time()
        if self._failing_since is None:
            self._failing_since = now
            _LOGGER.info("Lettura dal bridge fallita: nuovi tentativi ogni %s s per al massimo %s min",
                         BRIDGE_RETRY_SECONDS, BRIDGE_RETRY_WINDOW // 60)
        if now - self._failing_since < BRIDGE_RETRY_WINDOW:
            self.update_interval = timedelta(seconds=BRIDGE_RETRY_SECONDS)
        else:
            if self.update_interval != self._normal_interval:
                _LOGGER.info("Bridge ancora irraggiungibile dopo %s min: torno al ciclo normale", BRIDGE_RETRY_WINDOW // 60)
            self.update_interval = self._normal_interval

    @property
    def entities_available(self) -> bool:
        """Le entita' restano disponibili con l'ultimo valore finche' esiste un dato (anche a bridge fermo):
        lo stato e' descritto da dati_non_aggiornati. Non disponibili solo se non c'e' mai stato un dato."""
        return self.data is not None

    @property
    def connected(self) -> bool:
        """Bridge raggiungibile e Box collegata (secondo l'ultimo aggiornamento)."""
        d = self.data
        return bool(self.last_update_success and d and d.box_connected and d.mqtt_connected)

    @property
    def data_not_current(self) -> bool:
        """Dati da non considerare reali: ultimo dato oltre stale_minutes, oppure Box scollegata da almeno
        box_offline_minutes (le cadute brevi non cambiano nulla)."""
        if self.data is None:
            return True
        stale = self.config_entry.options.get(CONF_STALE_MINUTES, DEFAULT_STALE_MINUTES)
        return (time.time() - self.data.data_ts) / 60 > stale or self.monitor.confirmed_offline

    async def async_ensure_connected(self) -> None:
        """Prima di un comando dell'utente: se risulta scollegata rilegge, poi rifiuta (nessuna coda)."""
        if not self.connected:
            await self.async_refresh()
        if not self.last_update_success:
            raise AldesBridgeConnectionError("Bridge non raggiungibile")
        if not self.connected:
            raise AldesBoxNotConnectedError("Box non collegata al bridge")

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

    async def async_send_vacation(
        self,
        *,
        end_ts: float | None = None,
        guard: Callable[[], bool] | None = None,
        force_verify: bool = False,
        source: str = "ha",
    ) -> None:
        """Vacanza: changeMode con UNA stringa "W" + inizio + fine (UTC, YYYYMMDDHHMMSSZ).

        La data di fine e' solo di sicurezza: la Vacanza non ha un timer di rientro. end_ts: fine gia' decisa
        (ripristino); altrimenti adesso + giorni di Vacanza.
        """
        days = self.config_entry.options.get(CONF_VACATION_DAYS, DEFAULT_VACATION_DAYS)
        start = dt_util.utcnow().replace(microsecond=0)
        end = dt_util.utc_from_timestamp(end_ts).replace(microsecond=0) if end_ts else start + timedelta(days=days)
        fmt = "%Y%m%d%H%M%S"
        param = f"{MODE_VACATION}{start.strftime(fmt)}Z{end.strftime(fmt)}Z"
        await self.async_send_mode(
            MODE_VACATION, [param], vacation=(start.timestamp(), end.timestamp()),
            guard=guard, force_verify=force_verify, source=source,
        )

    async def async_record_refused(self, option_code: str) -> None:
        """Comando Quotidiano/Vacanza rifiutato (Box scollegata): l'obiettivo si aggiorna comunque."""
        vacation = None
        if option_code == MODE_VACATION:
            days = self.config_entry.options.get(CONF_VACATION_DAYS, DEFAULT_VACATION_DAYS)
            now = dt_util.utcnow().replace(microsecond=0)
            vacation = (now.timestamp(), (now + timedelta(days=days)).timestamp())
        await self.restore.async_record_command(option_code, vacation=vacation, delivered=False)

    async def _async_send(
        self, method: str, params: list[Any], guard: Callable[[], bool] | None = None
    ) -> float:
        """Invia rispettando la pausa minima (i comandi ravvicinati aspettano, non si perdono).

        Restituisce l'istante dell'invio."""
        async with self._send_lock:
            if self._last_send is not None:
                wait = COMMAND_MIN_INTERVAL - (time.monotonic() - self._last_send)
                if wait > 0:
                    _LOGGER.debug("Comando in attesa %.0f s (pausa minima)", wait)
                    await asyncio.sleep(wait)
            if guard is not None and not guard():
                raise CommandSuperseded()  # nel frattempo e' arrivato un comando piu' recente
            sent_at = time.time()
            await self.client.send_command(self.client_id, method, params)
            self._last_send = time.monotonic()
            await self.restore.async_note_send(sent_at)
            return sent_at

    async def async_send_mode(
        self,
        code: str,
        params: list[str] | None = None,
        *,
        timer_end: float | None = None,
        vacation: tuple[float, float] | None = None,
        guard: Callable[[], bool] | None = None,
        force_verify: bool = False,
        source: str = "ha",
    ) -> None:
        """Invia changeMode, poi verifica che la Box lo esegua (un solo nuovo invio).

        force_verify: verifica anche se la Box dichiara gia' quella modalita' (ripristino): serve un
        messaggio NUOVO della Box dopo l'invio.
        """
        params = params or [code]
        previous = self.data.mode_code if self.data else None
        sent_at = await self._async_send("changeMode", params, guard)
        await self.restore.async_record_command(code, timer_end=timer_end, vacation=vacation, source=source)
        self.pending_code = code
        self._pending_since = sent_at
        self.async_update_listeners()
        self._schedule_followups()
        self._cancel_verification()
        if previous != code or force_verify:
            self._verify_task = self.config_entry.async_create_background_task(
                self.hass,
                self._async_verify(code, params, sent_at, strict=force_verify),
                "aldes_vmc verifica comando",
            )

    def _cancel_verification(self) -> None:
        if self._verify_task and not self._verify_task.done():
            self._verify_task.cancel()
        self._verify_task = None

    async def _async_verify(
        self, code: str, params: list[str], sent_at: float, *, strict: bool = False
    ) -> None:
        """Entro COMMAND_VERIFY_TIMEOUT la Box deve riportare la modalita'; se no, un nuovo invio."""
        for attempt in (1, 2):
            await asyncio.sleep(COMMAND_VERIFY_TIMEOUT)
            await self.async_refresh()
            d = self.data
            # strict (ripristino con la Box che dichiara gia' quella modalita'): serve un messaggio
            # successivo all'invio, non quello che ha fatto decidere il ripristino
            fresh = d is not None and (d.data_ts > sent_at if strict else d.data_ts >= sent_at - 2)
            if d is not None and d.mode_code == code and fresh:
                self.last_command_error = None
                self.restore.on_command_confirmed(code)
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
        self.restore.on_command_unconfirmed(code)
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
