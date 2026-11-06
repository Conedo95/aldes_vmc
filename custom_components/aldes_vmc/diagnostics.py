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
        "kitchen_rientro_in_sospeso_dal": c.kitchen.pending_since.isoformat() if c.kitchen.pending_since else None,
        "boost_rientro_in_sospeso_dal": c.boost.pending_since.isoformat() if c.boost.pending_since else None,
        "box_scollegata_dal": c.monitor.offline_since,
        "riparazione_box_scollegata": c.monitor.issue_active,
        "dati_non_aggiornati": c.data_not_current,
        "obiettivo": {k: v for k, v in c.restore.goal.__dict__.items()},
        "ripristino": {
            "fase": c.restore.phase, "armato": c.restore.armed, "motivo": c.restore.armed_reason,
            "messaggi_dopo_ritorno": c.restore.messages, "ultimo_ripristino": c.restore.last_restore,
        },
        "pending_code": c.pending_code,
        "ultimo_errore_comando": c.last_command_error,
    }
