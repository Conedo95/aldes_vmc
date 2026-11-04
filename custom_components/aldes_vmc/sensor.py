"""Sensori."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature, UnitOfTime, UnitOfVolumeFlowRate
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import MODE_NAMES
from .coordinator import AldesCoordinator, AldesData
from .entity import AldesEntity


@dataclass(frozen=True, kw_only=True)
class AldesSensorDescription(SensorEntityDescription):
    """Descrizione con funzione di lettura."""

    value_fn: Callable[[AldesData], Any]


def _field(name: str) -> Callable[[AldesData], Any]:
    return lambda d: d.payload.get(name)


_TEMP = dict(
    device_class=SensorDeviceClass.TEMPERATURE,
    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=1,
)
_FLOW = dict(
    device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
    native_unit_of_measurement=UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=0,
)
_RPM = dict(
    native_unit_of_measurement="rpm",
    state_class=SensorStateClass.MEASUREMENT,
    icon="mdi:fan",
)
_DIAG = dict(
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
    state_class=SensorStateClass.MEASUREMENT,
)

SENSORS: tuple[AldesSensorDescription, ...] = (
    AldesSensorDescription(key="temperatura_esterna", value_fn=_field("outside_tpt"), **_TEMP),
    AldesSensorDescription(key="temperatura_estratta", value_fn=_field("ext_tpt"), **_TEMP),
    # reject_tpt: nel bridge si chiama cosi', ma e' l'aria immessa dopo lo scambiatore (confermato)
    AldesSensorDescription(key="temperatura_reimmessa", value_fn=_field("reject_tpt"), **_TEMP),
    AldesSensorDescription(key="portata_immissione", value_fn=_field("ffe_flw"), **_FLOW),
    AldesSensorDescription(key="portata_estrazione", value_fn=_field("extf_flw"), **_FLOW),
    AldesSensorDescription(key="giri_ventilatore_immissione", value_fn=_field("vi_spd"), **_RPM),
    AldesSensorDescription(key="giri_ventilatore_estrazione", value_fn=_field("extf_spd"), **_RPM),
    AldesSensorDescription(
        key="velocita_impostata",
        value_fn=_field("set_spd"),
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fan-speed-1",
    ),
    AldesSensorDescription(
        key="contatore_filtri",  # ff_cpt = usura filtri in % (troncata)
        value_fn=_field("ff_cpt"),
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:air-filter",
    ),
    AldesSensorDescription(
        key="indicatore_depressione",  # da verificare
        value_fn=_field("dep_ind"),
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gauge",
    ),
    AldesSensorDescription(
        key="modalita_attuale",
        value_fn=lambda d: MODE_NAMES.get(d.mode_code, d.mode_code) if d.mode_code else None,
        icon="mdi:fan-auto",
    ),
    AldesSensorDescription(
        key="ultimo_dato",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: dt_util.utc_from_timestamp(d.data_ts),
    ),
    # Diagnostici disattivati di default (oggi sempre 0)
    AldesSensorDescription(key="dtb_ind", value_fn=_field("dtb_ind"), **_DIAG),
    AldesSensorDescription(key="echange_pwr", value_fn=_field("echange_pwr"), **_DIAG),
    AldesSensorDescription(key="cve_csn", value_fn=_field("cve_csn"), **_DIAG),
    AldesSensorDescription(key="vi_csn", value_fn=_field("vi_csn"), **_DIAG),
    AldesSensorDescription(key="tte_csn", value_fn=_field("tte_csn"), **_DIAG),
    AldesSensorDescription(key="co2", value_fn=_field("Co2_vmc"), **_DIAG),
    AldesSensorDescription(key="pm25", value_fn=_field("Pm25_Vmc"), **_DIAG),
    AldesSensorDescription(key="voc", value_fn=_field("Voc_Vmc"), **_DIAG),
)


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator: AldesCoordinator = entry.runtime_data
    entities: list[SensorEntity] = [AldesSensor(coordinator, d) for d in SENSORS]
    entities.append(AldesLevelEndSensor(coordinator, "fine_cucina", coordinator.kitchen))
    entities.append(AldesLevelEndSensor(coordinator, "fine_boost", coordinator.boost))
    entities.append(AldesFilterDaysSensor(coordinator))
    async_add_entities(entities)


class AldesSensor(AldesEntity, SensorEntity):
    entity_description: AldesSensorDescription

    def __init__(self, coordinator: AldesCoordinator, description: AldesSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key == "modalita_attuale":
            return {"codice": self.coordinator.data.mode_code}
        return None


class AldesLevelEndSensor(AldesEntity, SensorEntity):
    """Ora di fine di Cucina o Boost (vuoto se non attivo)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator: AldesCoordinator, key: str, timer) -> None:
        super().__init__(coordinator, key)
        self._timer = timer

    @property
    def native_value(self) -> datetime | None:
        return self._timer.end


class AldesFilterDaysSensor(AldesEntity, SensorEntity):
    """Giorni rimanenti prima del cambio dei filtri (dall'ultimo reset dal display)."""

    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:air-filter"

    def __init__(self, coordinator: AldesCoordinator) -> None:
        super().__init__(coordinator, "giorni_filtri_rimanenti")

    @property
    def native_value(self) -> int | None:
        info = self.coordinator.filters.info()
        return info.remaining_days if info else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        info = self.coordinator.filters.info()
        if info is None:
            return None
        return {
            "data_ultimo_reset": info.last_reset.isoformat(),
            "giorni_trascorsi": info.elapsed_days,
            "durata_giorni": info.duration_days,
            "usura_calcolata_percentuale": info.wear_percent,
        }
