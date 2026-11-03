"""Sensore di connessione."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory

from .const import CONF_STALE_MINUTES, DEFAULT_STALE_MINUTES
from .entity import AldesEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([AldesConnectionSensor(entry.runtime_data)])


class AldesConnectionSensor(AldesEntity, BinarySensorEntity):
    """Acceso se Box e bridge sono collegati."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "connessione")

    @property
    def is_on(self) -> bool:
        d = self.coordinator.data
        return d.box_connected and d.mqtt_connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data
        stale = self.coordinator.config_entry.options.get(
            CONF_STALE_MINUTES, DEFAULT_STALE_MINUTES
        )
        age_min = (time.time() - d.data_ts) / 60
        return {
            "box_collegata": d.box_connected,
            "mqtt_bridge": d.mqtt_connected,
            "uptime_bridge_s": d.bridge_uptime,
            "eta_ultimo_dato_min": round(age_min, 1),
            "dati_obsoleti": age_min > stale,
        }
