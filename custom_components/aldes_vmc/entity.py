"""Entita' base."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AldesCoordinator


class AldesEntity(CoordinatorEntity[AldesCoordinator]):
    """Base con il dispositivo unico."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AldesCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.client_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        payload = self.coordinator.data.payload if self.coordinator.data else {}
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.client_id)},
            name="VMC Aldes",
            manufacturer="Aldes",
            model="InspirAIR Home S",
            sw_version=str(payload.get("Vers_UC")) if payload.get("Vers_UC") else None,
            configuration_url=f"http://{self.coordinator.client.host}:{self.coordinator.client.port}",
        )
