"""Pulsante di aggiornamento immediato (diagnostica)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .entity import AldesEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([AldesRefreshButton(entry.runtime_data)])


class AldesRefreshButton(AldesEntity, ButtonEntity):
    """Rilegge subito lo stato dal bridge (nessun comando alla Box)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "aggiorna")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
