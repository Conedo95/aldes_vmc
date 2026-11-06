"""Stato obiettivo persistito e ripristino della modalita' dopo una riconnessione della Box.

Regole (v0.2.1):
- lo "stato obiettivo" e' l'ultima modalita' voluta (comando di Home Assistant consegnato, oppure
  Quotidiano/Vacanza rifiutato perche' la Box era scollegata, oppure un cambio osservato dal display
  con la Box stabile);
- al passaggio offline -> online, solo se l'assenza e' stata >= box_offline_minutes (oppure c'e' un
  comando rifiutato non consegnato) si attendono 2 messaggi consecutivi della Box e poi si invia UN comando;
- il comando si invia anche se la Box dichiara gia' quella modalita' (funziona da sblocco);
- la conferma verifica solo che la Box RIPORTI la modalita' in un messaggio nuovo: non accerta l'effetto
  fisico sulla macchina (il 4/11/2026 la Box dichiarava V mentre i ventilatori giravano ancora a livello Cucina).
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import AldesBridgeError, CommandSuperseded
from .const import (
    BOOST_EXTERNAL_CHANGE_GRACE,
    COMMAND_MIN_INTERVAL,
    CONF_RESTORE_AFTER_RECONNECT,
    CONF_STALE_MINUTES,
    DEFAULT_RESTORE_AFTER_RECONNECT,
    DEFAULT_STALE_MINUTES,
    DOMAIN,
    ISSUE_RESTORE_FAILED,
    MODE_BOOST,
    MODE_DAILY,
    MODE_KITCHEN,
    MODE_NAMES,
    MODE_VACATION,
    PENDING_RETURN_MAX_AGE,
    RESTORE_STABLE_MESSAGES,
    STORAGE_VERSION,
)

if TYPE_CHECKING:
    from .coordinator import AldesCoordinator, AldesData

_LOGGER = logging.getLogger(__name__)
KNOWN = (MODE_DAILY, MODE_VACATION, MODE_KITCHEN, MODE_BOOST)


@dataclass
class Goal:
    mode: str | None = None
    commanded_at: float | None = None
    timer_end: float | None = None  # Cucina/Boost: scadenza (epoch)
    vacation_start: float | None = None
    vacation_end: float | None = None  # solo se la Vacanza e' stata comandata da Home Assistant
    source: str = "ha"  # ha | restore | observed
    undelivered: bool = False  # comando rifiutato (Box scollegata), da consegnare al ritorno
    version: int = 0


@dataclass
class Decision:
    action: str  # send | none | cancel | giveup
    code: str | None = None
    vacation_end: float | None = None
    reason: str = ""


def decide(
    goal: Goal, declared: str | None, now: float, *, timer_active: bool = False, timer_pending: bool = False
) -> Decision:
    """Cosa fare alla fine della stabilita' (funzione pura, provata nei test)."""
    mode = goal.mode
    if mode == MODE_DAILY:
        return Decision("send", MODE_DAILY, reason="obiettivo Quotidiano")
    if mode == MODE_VACATION:
        if goal.vacation_end is None:
            return Decision("none", reason="Vacanza impostata dal display: data di fine sconosciuta, non invio")
        if goal.vacation_end > now:
            return Decision("send", MODE_VACATION, goal.vacation_end, "obiettivo Vacanza con data di fine valida")
        return Decision("send", MODE_DAILY, reason="Vacanza con data di fine trascorsa")
    if mode in (MODE_KITCHEN, MODE_BOOST):
        if timer_active:
            return Decision("none", reason="timer in corso")
        if timer_pending:
            return Decision("none", reason="rientro gia' gestito dal rientro in sospeso")
        if goal.timer_end is None:
            return Decision("none", reason="scadenza del timer sconosciuta, non invio")
        if goal.timer_end > now:
            return Decision("none", reason="timer ancora valido")
        if now - goal.timer_end > PENDING_RETURN_MAX_AGE:
            return Decision("giveup", reason="timer scaduto da oltre 12 ore")
        if declared in (MODE_DAILY, mode):
            return Decision("send", MODE_DAILY, reason="timer scaduto")
        return Decision("cancel", reason=f"la Box dichiara {declared}: cambio fatto altrove, non invio")
    return Decision("none", reason="nessun obiettivo noto")


class RestoreManager:
    """Obiettivo persistito + macchina a stati offline -> ritorno -> stabile."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: AldesCoordinator) -> None:
        self.hass = hass
        self._entry = entry
        self._c = coordinator
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.goal")
        self.goal = Goal()
        self.phase = "stable"  # offline | returning | stable
        self.armed = False
        self.armed_reason: str | None = None
        self.messages = 0
        self.absence_s: float | None = None
        self.last_restore: dict[str, Any] | None = None
        self.last_send_epoch: float | None = None
        self.failed_issue = False
        self._offline_start: float | None = None
        self._return_ts: float | None = None
        self._last_counted: float | None = None
        self._last_seen_ts: float | None = None
        self._first = True
        self._task = None
        self._active_code: str | None = None

    # ---- persistenza -------------------------------------------------------
    @property
    def issue_id(self) -> str:
        return f"{ISSUE_RESTORE_FAILED}_{self._entry.entry_id}"

    @property
    def enabled(self) -> bool:
        return bool(self._entry.options.get(CONF_RESTORE_AFTER_RECONNECT, DEFAULT_RESTORE_AFTER_RECONNECT))

    async def async_load(self) -> None:
        s = await self._store.async_load() or {}
        g = s.get("goal") or {}
        self.goal = Goal(**{k: g[k] for k in Goal.__dataclass_fields__ if k in g})
        self._offline_start = s.get("offline_start")
        self.last_restore = s.get("last_restore")
        self.last_send_epoch = s.get("last_send")
        self.armed = bool(s.get("armed")) and self.goal.undelivered
        self.armed_reason = s.get("armed_reason") if self.armed else None
        if self._offline_start is not None:
            self.phase = "offline"
        elif self.armed:
            self.phase = "returning"
            self._return_ts = s.get("return_ts") or time.time()
        if self.last_send_epoch:
            age = time.time() - self.last_send_epoch
            if 0 <= age < COMMAND_MIN_INTERVAL:  # la pausa di 30 s vale anche attraverso un riavvio
                self._c._last_send = time.monotonic() - age

    async def async_save(self) -> None:
        await self._store.async_save(
            {
                "goal": asdict(self.goal),
                "offline_start": self._offline_start,
                "last_restore": self.last_restore,
                "last_send": self.last_send_epoch,
                "armed": self.armed,
                "armed_reason": self.armed_reason,
                "return_ts": self._return_ts,
            }
        )

    async def async_note_send(self, epoch: float) -> None:
        self.last_send_epoch = epoch
        await self.async_save()

    # ---- obiettivo ---------------------------------------------------------
    async def async_record_command(
        self,
        code: str,
        *,
        timer_end: float | None = None,
        vacation: tuple[float, float] | None = None,
        delivered: bool = True,
        source: str = "ha",
    ) -> None:
        """Aggiorna l'obiettivo. delivered=False: comando rifiutato (Box scollegata), da consegnare al ritorno."""
        g = self.goal
        g.version += 1
        g.mode, g.commanded_at, g.timer_end, g.source = code, time.time(), timer_end, source
        g.vacation_start, g.vacation_end = (vacation if vacation else (None, None))
        g.undelivered = not delivered
        if not delivered:
            self.armed, self.armed_reason = True, "comando rifiutato (Box non collegata)"
            if self.phase == "stable":
                self.phase, self._return_ts = "returning", time.time()
                self.messages, self._last_counted = 0, None
            _LOGGER.warning(
                "Comando %s rifiutato (Box non collegata): obiettivo aggiornato, sara' consegnato al ritorno della Box",
                MODE_NAMES.get(code, code),
            )
        elif self.armed and self.armed_reason and self.armed_reason.startswith("comando"):
            self.armed, self.armed_reason = False, None  # consegnato per altra via
        await self.async_save()

    async def async_set_timer_end(self, end_ts: float | None) -> None:
        self.goal.timer_end = end_ts
        await self.async_save()

    # ---- macchina a stati --------------------------------------------------
    def gate_open(self) -> bool:
        """Il rientro in sospeso di un timer aspetta la stessa stabilita' del ripristino quando e' armato."""
        return (not self.armed) or self.messages >= RESTORE_STABLE_MESSAGES

    async def async_process(self, data: AldesData | None, connected: bool) -> None:
        now = time.time()
        first, self._first = self._first, False
        threshold = self._c.monitor.threshold_minutes * 60
        if not connected:
            if self.phase != "offline":
                self.phase, self.messages, self._last_counted = "offline", 0, None
                if self._offline_start is None:
                    # prima lettura dopo un avvio: l'inizio dell'assenza e' al piu' l'ultimo dato noto
                    self._offline_start = min(now, data.data_ts) if (first and data and data.data_ts) else now
                await self.async_save()
            return
        assert data is not None
        if self.phase == "offline":
            start = self._offline_start or now
            self.absence_s = now - start
            self._return_ts, self.phase = start, "returning"
            self.messages, self._last_counted, self._offline_start = 0, None, None
            if self.enabled and not self.armed and self.absence_s >= threshold and self.goal.mode:
                self.armed, self.armed_reason = True, f"assenza di {self.absence_s / 60:.0f} minuti"
            _LOGGER.info(
                "Box di nuovo collegata dopo %.0f minuti%s",
                self.absence_s / 60,
                f": ripristino in attesa di {RESTORE_STABLE_MESSAGES} messaggi consecutivi ({self.armed_reason})"
                if self.armed
                else (" (sotto la soglia: nessun ripristino)" if self.absence_s < threshold else ""),
            )
            await self.async_save()
        if self.phase == "returning":
            if data.data_ts > (self._return_ts or 0) and (
                self._last_counted is None or data.data_ts > self._last_counted
            ):
                self._last_counted = data.data_ts
                self.messages += 1
            if self.messages >= RESTORE_STABLE_MESSAGES:
                self.phase = "stable"
                self._last_seen_ts = data.data_ts
                if self.armed and self.enabled:
                    await self._async_decide(data)
                elif self.armed:  # opzione disattivata: nessun invio automatico
                    _LOGGER.info("Ripristino dopo riconnessione disattivato nelle opzioni: nessun invio")
                    self.armed, self.armed_reason = False, None
                    await self.async_save()
            return
        await self._async_observe(data, now)

    async def _async_observe(self, data: AldesData, now: float) -> None:
        """Box stabile: un cambio di modalita' fatto altrove (display) diventa il nuovo obiettivo.

        Mai durante il ritorno dopo una riconnessione: i primi messaggi dopo un'assenza (per esempio V dopo un
        blackout) non devono sovrascrivere l'obiettivo."""
        if self.armed or data.data_ts == self._last_seen_ts:
            return
        stale_min = self._c.config_entry.options.get(CONF_STALE_MINUTES, DEFAULT_STALE_MINUTES)
        if (now - data.data_ts) / 60 > stale_min or self._c.monitor.confirmed_offline:
            return  # dato vecchio: non e' una prova
        self._last_seen_ts = data.data_ts
        declared, g = data.mode_code, self.goal
        if declared not in KNOWN:
            return
        if g.mode is None:
            kt = next((t for t in self._c.timers if t.active), None)
            if kt is not None:
                await self.async_record_command(kt.code, timer_end=kt.end.timestamp(), source="observed")
            else:
                await self.async_record_command(declared, source="observed")
            return
        if (
            declared != g.mode
            and self._c.pending_code is None
            and not any(t.pending for t in self._c.timers)
            and (g.commanded_at is None or now - g.commanded_at > BOOST_EXTERNAL_CHANGE_GRACE)
        ):
            _LOGGER.info(
                "Modalita' cambiata altrove con la Box stabile (%s -> %s): nuovo obiettivo",
                MODE_NAMES.get(g.mode, g.mode), MODE_NAMES.get(declared, declared),
            )
            await self.async_record_command(declared, source="observed")

    # ---- decisione ed esecuzione -------------------------------------------
    async def _async_decide(self, data: AldesData) -> None:
        reason, self.armed, self.armed_reason = self.armed_reason, False, None
        g = self.goal
        timer = next((t for t in self._c.timers if t.code == g.mode), None)
        d = decide(
            g, data.mode_code, time.time(),
            timer_active=bool(timer and timer.active), timer_pending=bool(timer and timer.pending),
        )
        absence = f"{self.absence_s / 60:.0f} min" if self.absence_s is not None else "n.d."
        _LOGGER.info(
            "Ripristino (%s): obiettivo %s, la Box dichiara %s -> %s (%s)",
            reason, MODE_NAMES.get(g.mode, g.mode), MODE_NAMES.get(data.mode_code, data.mode_code), d.action, d.reason,
        )
        if d.action == "send":
            version, self._active_code = g.version, d.code
            self._task = self._entry.async_create_background_task(
                self.hass, self._async_execute(d, version, reason, absence, data.mode_code), "aldes_vmc ripristino"
            )
            await self.async_save()
            return
        if d.action == "cancel":  # la Box e' in un'altra modalita' (display): adotto, non invio
            await self.async_record_command(data.mode_code, source="observed")
        elif d.action == "giveup":
            _LOGGER.warning("Ripristino annullato: %s", d.reason)
            await self.async_record_command(MODE_DAILY, source="observed")
        else:
            g.undelivered = False
        self.last_restore = {
            "quando": dt_util.utcnow().isoformat(timespec="seconds"), "motivo": reason,
            "azione": d.action, "dettaglio": d.reason, "dichiarata": data.mode_code, "assenza": absence,
        }
        await self.async_save()

    async def _async_execute(
        self, d: Decision, version: int, reason: str | None, absence: str, declared: str | None
    ) -> None:
        c = self._c
        guard = lambda: self.goal.version == version  # noqa: E731 - obiettivo cambiato nel frattempo -> non inviare
        try:
            if d.code == MODE_VACATION:
                await c.async_send_vacation(end_ts=d.vacation_end, guard=guard, force_verify=True, source="restore")
            else:
                await c.async_send_mode(MODE_DAILY, guard=guard, force_verify=True, source="restore")
        except CommandSuperseded:
            _LOGGER.info("Ripristino annullato: nel frattempo e' stato dato un comando piu' recente")
            self._active_code = None
            return
        except AldesBridgeError as err:
            self._open_failed(d.code, f"invio non riuscito: {err}")
            self._active_code = None
            return
        self.last_restore = {
            "quando": dt_util.utcnow().isoformat(timespec="seconds"), "motivo": reason,
            "azione": f"inviato {MODE_NAMES.get(d.code, d.code)}", "dettaglio": d.reason,
            "dichiarata": declared, "assenza": absence, "confermato": None,
        }
        _LOGGER.info(
            "Ripristino: inviato %s (motivo: %s; la Box dichiarava %s). La conferma verifica solo che la Box "
            "riporti la modalita' in un messaggio nuovo: non accerta l'effetto fisico.",
            MODE_NAMES.get(d.code, d.code), reason, MODE_NAMES.get(declared, declared),
        )
        await self.async_save()

    # ---- esito della verifica (chiamato dal coordinatore) -------------------
    def on_command_confirmed(self, code: str) -> None:
        if self._active_code == code and self.last_restore is not None:
            self.last_restore["confermato"] = True
            _LOGGER.info("Ripristino confermato dalla Box (messaggio nuovo con modalita' %s)", MODE_NAMES.get(code, code))
        self._active_code = None
        self._clear_failed()

    def on_command_unconfirmed(self, code: str) -> None:
        if self._active_code == code:
            self._open_failed(code, "la Box non ha confermato il comando dopo il rinvio")
            self._active_code = None

    def _open_failed(self, code: str | None, detail: str) -> None:
        if self.last_restore is not None:
            self.last_restore["confermato"] = False
        _LOGGER.error("Ripristino non riuscito (%s): nessun altro tentativo, aperta la Riparazione", detail)
        ir.async_create_issue(
            self.hass, DOMAIN, self.issue_id, is_fixable=False, severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_RESTORE_FAILED,
            translation_placeholders={"mode": MODE_NAMES.get(code, str(code)), "detail": detail},
        )
        self.failed_issue = True

    def _clear_failed(self) -> None:
        if self.failed_issue:
            ir.async_delete_issue(self.hass, DOMAIN, self.issue_id)
            self.failed_issue = False

    def async_unload(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()

    def async_remove(self) -> None:
        ir.async_delete_issue(self.hass, DOMAIN, self.issue_id)
