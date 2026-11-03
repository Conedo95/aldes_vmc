"""Selettore modalita'."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError

from .api import AldesBridgeError
from .const import (
    MODE_BOOST,
    MODE_DAILY,
    MODE_NAMES,
    OPTION_BOOST,
    OPTION_DAILY,
    SELECT_OPTIONS,
)
from .entity import AldesEntity

_CODE_TO_OPTION = {MODE_DAILY: OPTION_DAILY, MODE_BOOST: OPTION_BOOST}


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([AldesModeSelect(entry.runtime_data)])


class AldesModeSelect(AldesEntity, SelectEntity):
    """Quotidiano / Boost (il Boost rientra da solo a Quotidiano)."""

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
        }

    async def async_select_option(self, option: str) -> None:
        try:
            if option == OPTION_BOOST:
                await self.coordinator.boost.async_start()
            else:
                await self.coordinator.boost.async_cancel()
                await self.coordinator.async_send_mode(MODE_DAILY)
        except AldesBridgeError as err:
            raise HomeAssistantError(f"Comando non inviato: {err}") from err
