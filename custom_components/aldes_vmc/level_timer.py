"""Timer di rientro (Cucina / Boost) che sopravvive al riavvio di Home Assistant.

Se alla scadenza la Box non e' collegata il rientro a Quotidiano non va perso: resta "in
sospeso" (salvato su disco) e viene inviato appena la Box torna collegata, al massimo entro
PENDING_RETURN_MAX_AGE (12 ore) dalla scadenza.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import AldesBoxNotConnectedError, AldesBridgeConnectionError, AldesBridgeError
from .const import (
    BOOST_EXTERNAL_CHANGE_GRACE,
    DOMAIN,
    MODE_DAILY,
    PENDING_RETURN_MAX_AGE,
    PENDING_RETURN_MAX_REJECTS,
    STORAGE_VERSION,
)

if TYPE_CHECKING:
    from .coordinator import AldesCoordinator, AldesData

_LOGGER = logging.getLogger(__name__)


class LevelTimer:
    """Ora di fine di un livello a tempo (Cucina o Boost) e rientro a Quotidiano."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: AldesCoordinator,
        *,
        name: str,
        code: str,
        option_key: str,
        default_minutes: int,
        store_suffix: str = "",
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self.name = name
        self.code = code
        self._option_key = option_key
        self._default_minutes = default_minutes
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}{store_suffix}"
        )
        self.end: datetime | None = None
        self._started: float | None = None
        # Rientro dovuto da questo istante ma non ancora inviato (Box scollegata)
        self.pending_since: datetime | None = None
        # Solo un messaggio della Box con timestamp successivo a questo istante (epoch) e' "nuovo":
        # decide se inviare il rientro. E' il momento del tentativo fallito (Box scollegata).
        self._pending_after: float | None = None
        self._unsub: CALLBACK_TYPE | None = None
        self._pending_task: asyncio.Task | None = None
        self._finishing = False
        self._rejects = 0

    @property
    def active(self) -> bool:
        return self.end is not None

    @property
    def pending(self) -> bool:
        return self.pending_since is not None

    async def async_load(self) -> None:
        """Ripristina il timer (o il rientro in sospeso) dopo un riavvio."""
        stored = await self._store.async_load() or {}
        pending = dt_util.parse_datetime(stored.get("pending_since", "") or "")
        if pending is not None:
            self.pending_since = pending
            after = stored.get("pending_after")
            self._pending_after = float(after) if after is not None else pending.timestamp()
            _LOGGER.info(
                "%s: rientro a Quotidiano in sospeso dalle %s, riprovo appena la Box e' collegata",
                self.name, pending,
            )
            return
        end = dt_util.parse_datetime(stored.get("end", "") or "")
        if end is None:
            return
        self._started = stored.get("started")
        self.end = end
        if end <= dt_util.utcnow():
            _LOGGER.info("%s scaduto durante lo spegnimento: rientro a Quotidiano", self.name)
            self.hass.async_create_task(self._async_finish())
        else:
            _LOGGER.info("%s ripreso dopo il riavvio, fine alle %s", self.name, end)
            self._schedule(end)

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "mode": self.code,
                "end": self.end.isoformat() if self.end else None,
                "started": self._started,
                "pending_since": self.pending_since.isoformat() if self.pending_since else None,
                "pending_after": self._pending_after if self.pending_since else None,
            }
        )

    def _schedule(self, end: datetime) -> None:
        if self._unsub:
            self._unsub()
        self._unsub = async_track_point_in_utc_time(self.hass, self._on_timer, end)

    @callback
    def _on_timer(self, _now: datetime) -> None:
        """Scadenza: gira nel loop di HA (callback marcata), quindi puo' pianificare il task."""
        self._unsub = None
        self.hass.async_create_task(self._async_finish())

    async def async_start(self) -> None:
        """Avvia il livello per la durata configurata."""
        minutes = self._entry.options.get(self._option_key, self._default_minutes)
        # Se l'invio fallisce l'eccezione sale e il timer non viene programmato
        await self._coordinator.async_send_mode(self.code)
        self._cancel_pending_task()
        self.pending_since = None
        self._pending_after = None
        self._rejects = 0
        self._started = dt_util.utcnow().timestamp()
        self.end = dt_util.utcnow() + timedelta(minutes=minutes)
        self._schedule(self.end)
        await self._coordinator.restore.async_set_timer_end(self.end.timestamp())
        await self._async_save()
        self._coordinator.async_update_listeners()

    async def async_cancel(self) -> None:
        """Annulla il timer (e un eventuale rientro in sospeso) senza inviare comandi."""
        if self._unsub:
            self._unsub()
            self._unsub = None
        self._cancel_pending_task()
        if self.end is not None or self.pending_since is not None:
            self.end = None
            self._started = None
            self.pending_since = None
            self._pending_after = None
            self._rejects = 0
            await self._async_save()
            self._coordinator.async_update_listeners()

    def _cancel_pending_task(self) -> None:
        task = self._pending_task
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
        self._pending_task = None

    async def _async_clear(self) -> None:
        self.end = None
        self._started = None
        self.pending_since = None
        self._pending_after = None
        self._rejects = 0
        await self._async_save()
        self._coordinator.async_update_listeners()

    async def _async_set_pending(self, err: Exception) -> None:
        """Il rientro non e' stato inviato: lo ricordo (e lo salvo) per riprovare al ritorno della Box."""
        now = dt_util.utcnow()
        if self.pending_since is None:
            # il limite di 12 ore parte dalla scadenza, non dal primo tentativo fallito
            self.pending_since = min(self.end, now) if self.end else now
            self._pending_after = now.timestamp()
            _LOGGER.warning(
                "%s: rientro a Quotidiano non inviato (%s). Resta in sospeso (massimo 12 ore) "
                "e verra' inviato appena la Box e' collegata",
                self.name, err,
            )
        else:
            _LOGGER.debug("%s: rientro ancora in sospeso (%s)", self.name, err)
        self.end = None
        self._started = None
        await self._async_save()
        self._coordinator.async_update_listeners()

    async def _async_finish(self) -> None:
        """Fine del livello: torna a Quotidiano; se non si puo', il rientro resta in sospeso."""
        if self._finishing:
            return
        self._finishing = True
        try:
            try:
                await self._coordinator.async_send_mode(MODE_DAILY)
            except (AldesBoxNotConnectedError, AldesBridgeConnectionError) as err:
                await self._async_set_pending(err)
                return
            except AldesBridgeError as err:
                # comando rifiutato dal bridge per un altro motivo: poche altre prove, poi rinuncio
                self._rejects += 1
                if self._rejects >= PENDING_RETURN_MAX_REJECTS:
                    _LOGGER.error(
                        "%s: impossibile tornare a Quotidiano (%s), rinuncio dopo %s tentativi",
                        self.name, err, self._rejects,
                    )
                    await self._async_clear()
                else:
                    await self._async_set_pending(err)
                return
            was_pending = self.pending_since is not None
            await self._async_clear()
            if was_pending:
                _LOGGER.info("%s: rientro a Quotidiano in sospeso inviato", self.name)
        finally:
            self._finishing = False

    async def _async_handle_pending(self, data: AldesData) -> None:
        """Rientro in sospeso: lo invia quando la Box e' collegata (entro 12 ore)."""
        assert self.pending_since is not None
        age = (dt_util.utcnow() - self.pending_since).total_seconds()
        if age > PENDING_RETURN_MAX_AGE:
            _LOGGER.warning(
                "%s: rientro a Quotidiano in sospeso da oltre 12 ore, annullato senza inviare",
                self.name,
            )
            await self._async_clear()
            return
        if not (data.box_connected and data.mqtt_connected):
            return
        after = self._pending_after if self._pending_after is not None else self.pending_since.timestamp()
        if data.mode_code is None or data.data_ts <= after:
            # Box ricollegata ma nessun messaggio NUOVO: il dato in memoria e' quello di prima
            # del silenzio, non dice cosa sta facendo ora la VMC. Aspetto il prossimo.
            _LOGGER.debug("%s: Box collegata, attendo un messaggio nuovo prima di decidere", self.name)
            return
        if not self._coordinator.restore.gate_open():
            _LOGGER.debug("%s: ripristino dopo riconnessione in attesa di messaggi consecutivi", self.name)
            return
        if data.mode_code not in (MODE_DAILY, self.code):
            _LOGGER.info(
                "%s: nel dato nuovo la Box e' in un'altra modalita' (%s, non %s ne' Quotidiano): "
                "rientro in sospeso annullato, non invio nulla",
                self.name, data.mode_code, self.code,
            )
            await self._async_clear()
            return
        if self._finishing or (self._pending_task and not self._pending_task.done()):
            return
        _LOGGER.info(
            "%s: dato nuovo, la Box dichiara %s: invio il rientro a Quotidiano in sospeso (anche se dichiara gia' Quotidiano: sblocco)",
            self.name, data.mode_code,
        )
        # In background: l'invio rispetta la pausa di 30 s e non deve bloccare l'aggiornamento dati
        self._pending_task = self._entry.async_create_background_task(
            self.hass, self._async_finish(), f"aldes_vmc rientro in sospeso {self.name}"
        )

    async def async_data_updated(self, data: AldesData) -> None:
        """Rientro in sospeso da inviare, oppure livello cambiato altrove (timer da annullare)."""
        if self.pending_since is not None:
            await self._async_handle_pending(data)
            return
        if not self.active or self._started is None:
            return
        if self._coordinator.pending_code is not None:
            return  # comando in attesa di conferma (o nuovo invio in corso)
        if (
            data.data_ts > self._started + BOOST_EXTERNAL_CHANGE_GRACE
            and data.mode_code is not None
            and data.mode_code != self.code
        ):
            _LOGGER.info(
                "Modalita' cambiata altrove (%s): timer %s annullato", data.mode_code, self.name
            )
            await self.async_cancel()

    @callback
    def async_unload(self) -> None:
        """Ferma i timer in memoria (lo stato salvato resta)."""
        if self._unsub:
            self._unsub()
            self._unsub = None
        self._cancel_pending_task()
