"""Selettore modalita'."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity

from .api import AldesBridgeError
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
        code = self.coordinator.pending_code or self.coordinator.data.mode_code
        return _CODE_TO_OPTION.get(code)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data
        return {
            "in_attesa_di_conferma": self.coordinator.pending_code is not None,
            "modalita_reale": MODE_NAMES.get(d.mode_code, d.mode_code),
            "ultimo_errore_comando": self.coordinator.last_command_error,
        }

    async def async_select_option(self, option: str) -> None:
        c = self.coordinator
        try:
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
            raise command_error(err) from err
