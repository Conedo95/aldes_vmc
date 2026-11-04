"""Monitoraggio dei filtri: rileva da solo il reset fatto dal display.

La Box manda `ff_cpt` = percentuale di usura dei filtri (0-100, troncata). Il reset si
esegue dal display della macchina e riporta `ff_cpt` a 0: qui lo si riconosce e si salva la
data (quella del messaggio della Box) per calcolare i giorni rimanenti.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import AldesBridgeError
from .const import (
    CONF_FILTER_MONTHS,
    DAYS_PER_FILTER_MONTH,
    DEFAULT_FILTER_MONTHS,
    DOMAIN,
    FILTER_RESET_DROP,
    HISTORY_MAX_PAGES,
    HISTORY_PAGE_SIZE,
    STORAGE_VERSION,
)

if TYPE_CHECKING:
    from .coordinator import AldesCoordinator, AldesData

_LOGGER = logging.getLogger(__name__)


def is_reset(previous: float | None, current: float | None) -> bool:
    """True se ff_cpt e' sceso di almeno FILTER_RESET_DROP punti o e' passato da >0 a 0."""
    if previous is None or current is None:
        return False
    if previous > 0 and current == 0:
        return True
    return previous - current >= FILTER_RESET_DROP


def find_last_reset(series: list[tuple[float, float]]) -> float | None:
    """Timestamp dell'ultima transizione di reset in una serie (ts, ff) dal piu' recente."""
    for newer, older in zip(series, series[1:]):
        if is_reset(older[1], newer[1]):
            return newer[0]
    return None


def estimate_last_reset(now: datetime, ff_cpt: float, duration_days: int) -> datetime:
    return now - timedelta(days=ff_cpt / 100 * duration_days)


@dataclass
class FilterInfo:
    last_reset: datetime
    elapsed_days: int
    duration_days: int
    remaining_days: int
    wear_percent: float


class FilterTracker:
    """Data dell'ultimo reset, salvata in .storage/aldes_vmc.<entry_id>.filters."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, coordinator: AldesCoordinator
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.filters"
        )
        self.last_reset: datetime | None = None
        self._last_ff: float | None = None

    @property
    def duration_days(self) -> int:
        months = self._entry.options.get(CONF_FILTER_MONTHS, DEFAULT_FILTER_MONTHS)
        return int(months) * DAYS_PER_FILTER_MONTH

    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}
        self.last_reset = dt_util.parse_datetime(stored.get("last_reset") or "")
        self._last_ff = stored.get("last_ff")

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "last_reset": self.last_reset.isoformat() if self.last_reset else None,
                "last_ff": self._last_ff,
            }
        )

    async def async_data_updated(self, data: AldesData) -> None:
        ff = data.payload.get("ff_cpt")
        if not isinstance(ff, (int, float)):
            return
        if self.last_reset is None:
            await self._async_bootstrap(ff)
        elif is_reset(self._last_ff, ff):
            self.last_reset = dt_util.utc_from_timestamp(data.data_ts)
            _LOGGER.info("Reset filtri rilevato (ff_cpt %s -> %s)", self._last_ff, ff)
            self._last_ff = ff
            await self._async_save()
            return
        if ff != self._last_ff:
            self._last_ff = ff
            await self._async_save()

    async def _async_bootstrap(self, ff: float) -> None:
        """Primo avvio: data del reset dallo storico del bridge, altrimenti stima."""
        ts = None
        try:
            series = await self._coordinator.client.get_ff_history(
                HISTORY_PAGE_SIZE, HISTORY_MAX_PAGES
            )
            ts = find_last_reset(series)
        except AldesBridgeError as err:
            _LOGGER.debug("Storico ff_cpt non letto: %s", err)
        if ts is not None:
            self.last_reset = dt_util.utc_from_timestamp(ts)
            _LOGGER.info("Ultimo reset filtri trovato nello storico del bridge")
        else:
            self.last_reset = estimate_last_reset(
                dt_util.utcnow(), ff, self.duration_days
            )
            _LOGGER.info("Ultimo reset filtri stimato da ff_cpt")
        self._last_ff = ff
        await self._async_save()

    def info(self) -> FilterInfo | None:
        if self.last_reset is None:
            return None
        duration = self.duration_days
        elapsed = max(0.0, (dt_util.utcnow() - self.last_reset).total_seconds() / 86400)
        days = int(elapsed)
        return FilterInfo(
            last_reset=self.last_reset,
            elapsed_days=days,
            duration_days=duration,
            remaining_days=max(0, duration - days),
            wear_percent=round(min(100.0, elapsed / duration * 100), 1),
        )

    async def async_remove(self) -> None:
        await self._store.async_remove()
