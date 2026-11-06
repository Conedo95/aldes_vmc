"""Sensore di connessione."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.util import dt as dt_util

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
        """Box e bridge collegati. A bridge irraggiungibile mantiene l'ultimo valore (come i sensori) e diventa
        spento solo quando l'assenza e' confermata (>= box_offline_minutes)."""
        c = self.coordinator
        d = c.data
        if not c.last_update_success and c.monitor.confirmed_offline:
            return False
        return d.box_connected and d.mqtt_connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data
        stale = self.coordinator.config_entry.options.get(
            CONF_STALE_MINUTES, DEFAULT_STALE_MINUTES
        )
        age_min = (time.time() - d.data_ts) / 60
        return {
            "bridge_raggiungibile": self.coordinator.last_update_success,
            "box_collegata": d.box_connected,
            "mqtt_bridge": d.mqtt_connected,
            "uptime_bridge_s": d.bridge_uptime,
            "eta_ultimo_dato_min": round(age_min, 1),
            "dati_obsoleti": age_min > stale,
            "dati_non_aggiornati": self.coordinator.data_not_current,
            "scollegata_dalle": (
                dt_util.utc_from_timestamp(m.offline_since).isoformat()
                if (m := self.coordinator.monitor).offline_since
                else None
            ),
            "riparazione_attiva": self.coordinator.monitor.issue_active,
        }
