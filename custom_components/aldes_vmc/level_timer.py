"""Timer di rientro (Cucina / Boost) che sopravvive al riavvio di Home Assistant."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import AldesBridgeError
from .const import (
    BOOST_EXTERNAL_CHANGE_GRACE,
    DOMAIN,
    MODE_DAILY,
    STORAGE_VERSION,
)

if TYPE_CHECKING:
    from .coordinator import AldesCoordinator, AldesData

_LOGGER = logging.getLogger(__name__)
RETRY_SECONDS = 60
MAX_RETRIES = 5


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
        self._unsub: CALLBACK_TYPE | None = None
        self._retry_unsub: CALLBACK_TYPE | None = None
        self._retries = 0

    @property
    def active(self) -> bool:
        return self.end is not None

    async def async_load(self) -> None:
        """Ripristina il timer dopo un riavvio."""
        stored = await self._store.async_load() or {}
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
                "end": self.end.isoformat() if self.end else None,
                "started": self._started,
            }
        )

    def _schedule(self, end: datetime) -> None:
        if self._unsub:
            self._unsub()
        self._unsub = async_track_point_in_utc_time(
            self.hass, self._on_timer, end
        )

    @callback
    def _on_timer(self, _now: datetime) -> None:
        self._unsub = None
        self.hass.async_create_task(self._async_finish())

    async def async_start(self) -> None:
        """Avvia il livello per la durata configurata."""
        minutes = self._entry.options.get(self._option_key, self._default_minutes)
        # Se l'invio fallisce l'eccezione sale e il timer non viene programmato
        await self._coordinator.async_send_mode(self.code)
        self._cancel_retry()
        self._started = dt_util.utcnow().timestamp()
        self.end = dt_util.utcnow() + timedelta(minutes=minutes)
        self._schedule(self.end)
        await self._async_save()
        self._coordinator.async_update_listeners()

    async def async_cancel(self) -> None:
        """Annulla il timer senza inviare comandi."""
        if self._unsub:
            self._unsub()
            self._unsub = None
        self._cancel_retry()
        if self.end is not None:
            self.end = None
            self._started = None
            await self._async_save()
            self._coordinator.async_update_listeners()

    def _cancel_retry(self) -> None:
        if self._retry_unsub:
            self._retry_unsub()
            self._retry_unsub = None
        self._retries = 0

    async def _async_finish(self) -> None:
        """Fine del livello: torna a Quotidiano (con nuovi tentativi se l'invio fallisce)."""
        try:
            await self._coordinator.async_send_mode(MODE_DAILY)
        except AldesBridgeError as err:
            self._retries += 1
            if self._retries > MAX_RETRIES:
                _LOGGER.error("Impossibile tornare a Quotidiano dopo %s: %s", self.name, err)
                self._retries = 0
                self.end = None
                await self._async_save()
                self._coordinator.async_update_listeners()
                return
            _LOGGER.warning("Rientro a Quotidiano fallito (%s), riprovo", err)
            self._retry_unsub = async_call_later(
                self.hass,
                RETRY_SECONDS,
                lambda _n: self.hass.async_create_task(self._async_finish()),
            )
            return
        self._cancel_retry()
        self.end = None
        self._started = None
        await self._async_save()
        self._coordinator.async_update_listeners()

    async def async_data_updated(self, data: AldesData) -> None:
        """Se un dato recente mostra un'altra modalita', il livello e' stato cambiato altrove."""
        if not self.active or self._started is None or self._retry_unsub:
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
        self._cancel_retry()
