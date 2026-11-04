"""Diagnostica."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

SKIP = {"week_planning"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry) -> dict[str, Any]:
    c = entry.runtime_data
    d = c.data
    return {
        "entry": {"options": dict(entry.options), "host": "***", "port": entry.data.get("port")},
        "client_id": "***" + c.client_id[-4:],
        "payload": {k: v for k, v in d.payload.items() if k not in SKIP},
        "data_ts": d.data_ts,
        "mode_code": d.mode_code,
        "box_connected": d.box_connected,
        "mqtt_connected": d.mqtt_connected,
        "kitchen_end": c.kitchen.end.isoformat() if c.kitchen.end else None,
        "boost_end": c.boost.end.isoformat() if c.boost.end else None,
        "pending_code": c.pending_code,
        "ultimo_errore_comando": c.last_command_error,
    }
