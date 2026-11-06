"""Selettore modalita'."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.util import dt as dt_util

from .api import AldesBoxNotConnectedError, AldesBridgeConnectionError, AldesBridgeError
from .errors import command_error
from .const import (
    MODE_BOOST,
    MODE_DAILY,
    MODE_KITCHEN,
    MODE_NAMES,
    MODE_VACATION,
    OPTION_BOOST,
    OPTION_DAILY,
    OPTION_KITCHEN,
    OPTION_VACATION,
    SELECT_OPTIONS,
)
from .entity import AldesEntity

_CODE_TO_OPTION = {
    MODE_DAILY: OPTION_DAILY,
    MODE_KITCHEN: OPTION_KITCHEN,
    MODE_BOOST: OPTION_BOOST,
    MODE_VACATION: OPTION_VACATION,
}


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([AldesModeSelect(entry.runtime_data)])


class AldesModeSelect(AldesEntity, SelectEntity):
    """Vacanza / Quotidiano / Cucina / Boost (Cucina e Boost rientrano da soli a Quotidiano)."""

    _attr_options = SELECT_OPTIONS
    _attr_icon = "mdi:fan"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "modalita")

    @property
    def current_option(self) -> str | None:
        """Ultima modalita' nota. Con la Box scollegata NON diventa 'unknown': le automazioni che controllano
        il selettore devono poter scattare (il comando viene rifiutato e l'obiettivo si aggiorna). Per sapere se
        e' confermata c'e' l'attributo dati_non_aggiornati (le plance non evidenziano il tasto se e' vero)."""
        code = self.coordinator.pending_code or self.coordinator.data.mode_code
        return _CODE_TO_OPTION.get(code)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.coordinator
        d = c.data
        stale = c.data_not_current
        g = c.restore.goal
        pending = [t.pending_since.isoformat() for t in c.timers if t.pending_since is not None]
        return {
            "in_attesa_di_conferma": c.pending_code is not None and not stale,
            "modalita_reale": MODE_NAMES.get(d.mode_code, d.mode_code),
            "dati_non_aggiornati": stale,
            "obiettivo": MODE_NAMES.get(g.mode, g.mode),
            "obiettivo_non_consegnato": g.undelivered,
            "rientro_in_sospeso_dal": pending[0] if pending else None,
            "ultimo_ripristino": c.restore.last_restore,
            "ultimo_errore_comando": c.last_command_error,
        }

    async def async_select_option(self, option: str) -> None:
        c = self.coordinator
        try:
            # Box scollegata: errore subito, nessuna coda, lo stato mostrato non cambia
            await c.async_ensure_connected()
            if option == OPTION_KITCHEN:
                await c.kitchen.async_start()
                await c.async_cancel_timers(keep=c.kitchen)
            elif option == OPTION_BOOST:
                await c.boost.async_start()
                await c.async_cancel_timers(keep=c.boost)
            elif option == OPTION_VACATION:
                await c.async_cancel_timers()
                await c.async_send_vacation()
            else:
                await c.async_cancel_timers()
                await c.async_send_mode(MODE_DAILY)
        except AldesBridgeError as err:
            refused = isinstance(err, (AldesBoxNotConnectedError, AldesBridgeConnectionError))
            if refused and option in (OPTION_DAILY, OPTION_VACATION):
                # Comando rifiutato (Box scollegata, non messo in coda): l'obiettivo si aggiorna comunque, cosi' al
                # ritorno della Box viene consegnata la modalita' voluta. Cucina/Boost rifiutati non si recuperano.
                await c.async_cancel_timers()
                await c.async_record_refused(MODE_DAILY if option == OPTION_DAILY else MODE_VACATION)
            c.last_command_error = (
                f"{dt_util.now().isoformat(timespec='seconds')}: {option} non eseguito ({err})"
            )
            c.async_update_listeners()
            raise command_error(err) from err
