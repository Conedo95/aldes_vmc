"""Costanti per Aldes VMC (locale)."""

from __future__ import annotations

DOMAIN = "aldes_vmc"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_BOOST_MINUTES = "boost_minutes"
CONF_STALE_MINUTES = "stale_minutes"

DEFAULT_HOST = "homeassistant.local"
DEFAULT_PORT = 8080
DEFAULT_SCAN_INTERVAL = 300  # secondi
DEFAULT_BOOST_MINUTES = 30
DEFAULT_STALE_MINUTES = 30

MIN_SCAN_INTERVAL = 60
MAX_SCAN_INTERVAL = 900
MIN_BOOST_MINUTES = 1
MAX_BOOST_MINUTES = 240

# Codici modalita' della Box -> nome mostrato
MODE_DAILY = "V"
MODE_BOOST = "Y"
MODE_NAMES: dict[str, str] = {
    "V": "Quotidiano",
    "Y": "Boost",
    "X": "Ospiti",
    "Z": "Programma aria",
    "W": "Vacanze",
}

OPTION_DAILY = "Quotidiano"
OPTION_BOOST = "Boost"
SELECT_OPTIONS = [OPTION_DAILY, OPTION_BOOST]

# Tempo massimo in cui il select mostra la modalita' richiesta in attesa di conferma
PENDING_TIMEOUT = 20 * 60
# Dopo quanto tempo dall'avvio del Boost un dato con altra modalita' lo annulla
BOOST_EXTERNAL_CHANGE_GRACE = 120

SERVICE_SEND_COMMAND = "send_command"
STORAGE_VERSION = 1
