"""Controllo della connessione della Box: Riparazione "Box scollegata"."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BOX_OFFLINE_MINUTES,
    DEFAULT_BOX_OFFLINE_MINUTES,
    DOMAIN,
    ISSUE_BOX_OFFLINE,
    MIN_SILENCE_MINUTES,
)

if TYPE_CHECKING:
    from .coordinator import AldesCoordinator

_LOGGER = logging.getLogger(__name__)


class ConnectionMonitor:
    """Se la Box (o il bridge) resta scollegata oltre N minuti, o non manda messaggi, crea una Riparazione.

    Anti-rimbalzo: una caduta piu' breve di N minuti non apre nulla. "Nessun messaggio" vale solo oltre
    max(N, 30) minuti (MIN_SILENCE_MINUTES, costante interna): la Box ne manda uno ogni ~10 minuti e a volte
    ha buchi di 20-30 minuti con la rete instabile.

    La Riparazione non e' risolvibile dall'utente da qui (non fixable): sparisce da sola
    appena la connessione torna. Lo stato non e' persistente: dopo un riavvio di Core il
    conteggio dei minuti riparte da zero.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: AldesCoordinator) -> None:
        self.hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self.offline_since: float | None = None
        self.silent = False
        self.issue_active = False
        self._closed = False  # dopo lo scarico (o un avvio fallito) non apre piu' nulla
        self._unsub: CALLBACK_TYPE | None = None

    @property
    def issue_id(self) -> str:
        return f"{ISSUE_BOX_OFFLINE}_{self._entry.entry_id}"

    @property
    def threshold_minutes(self) -> int:
        return int(self._entry.options.get(CONF_BOX_OFFLINE_MINUTES, DEFAULT_BOX_OFFLINE_MINUTES))

    @property
    def confirmed_offline(self) -> bool:
        """Scollegata da almeno N minuti (le cadute brevi non contano)."""
        return (
            self.offline_since is not None
            and time.time() - self.offline_since >= self.threshold_minutes * 60
        )

    @callback
    def update(self, connected: bool, data_ts: float | None = None) -> None:
        """Da chiamare a ogni aggiornamento (anche fallito, con connected=False)."""
        if self._closed:
            return
        silence_limit = max(self.threshold_minutes, MIN_SILENCE_MINUTES) * 60
        self.silent = bool(connected and data_ts and time.time() - data_ts > silence_limit)
        if connected:
            self._back_online()
            if self.silent:
                self._open(reason="senza messaggi", since_ts=data_ts)
            return
        if self.offline_since is None:
            self.offline_since = time.time()
            _LOGGER.info("Box/bridge scollegati: avviso fra %s minuti", self.threshold_minutes)
        if self._unsub is None and not self.issue_active:
            self._schedule()
        self._check()

    def _schedule(self) -> None:
        if self._closed:
            return
        remaining = max(1.0, self.offline_since + self.threshold_minutes * 60 - time.time())
        self._unsub = async_call_later(self.hass, remaining, self._on_timer)

    @callback
    def _on_timer(self, _now) -> None:
        self._unsub = None
        if self._closed:
            return
        self._check()

    @callback
    def _check(self) -> None:
        if self.offline_since is None or not self.confirmed_offline:
            return
        self._open(reason="scollegata")

    def _open(self, *, reason: str, since_ts: float | None = None) -> None:
        if self.issue_active or self._closed:
            return
        client = self._coordinator.client
        since = dt_util.as_local(dt_util.utc_from_timestamp(since_ts or self.offline_since or time.time()))
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self.issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_BOX_OFFLINE,
            translation_placeholders={
                "minutes": str(self.threshold_minutes),
                "since": since.strftime("%d/%m %H:%M"),
                "bridge": f"{client.host}:{client.port}",
            },
        )
        self.issue_active = True
        _LOGGER.warning(
            "Box %s da oltre %s minuti: creata la Riparazione", reason, self.threshold_minutes
        )

    def _back_online(self) -> None:
        self._cancel_timer()
        self.offline_since = None
        if not self.silent:
            # si chiude solo con la connessione E un messaggio recente (idempotente dopo un ricaricamento)
            if self.issue_active:
                _LOGGER.info("Box di nuovo collegata: chiusa la Riparazione")
            ir.async_delete_issue(self.hass, DOMAIN, self.issue_id)
            self.issue_active = False

    def _cancel_timer(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    def async_unload(self) -> None:
        """Scarico o avvio fallito: ferma il timer e impedisce di aprire altre Riparazioni."""
        self._closed = True
        self._cancel_timer()

    @callback
    def async_remove(self) -> None:
        self._closed = True
        self._cancel_timer()
        ir.async_delete_issue(self.hass, DOMAIN, self.issue_id)
