"""Costanti per Aldes VMC (locale)."""

from __future__ import annotations

DOMAIN = "aldes_vmc"
VERSION = "0.2.1"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_KITCHEN_MINUTES = "kitchen_minutes"
CONF_BOOST_MINUTES = "boost_minutes"
CONF_STALE_MINUTES = "stale_minutes"
CONF_VACATION_DAYS = "vacation_days"
CONF_FILTER_MONTHS = "filter_months"
CONF_BOX_OFFLINE_MINUTES = "box_offline_minutes"
CONF_RESTORE_AFTER_RECONNECT = "restore_after_reconnect"

DEFAULT_HOST = "homeassistant.local"
DEFAULT_PORT = 8080
DEFAULT_SCAN_INTERVAL = 300  # secondi
DEFAULT_KITCHEN_MINUTES = 30
DEFAULT_BOOST_MINUTES = 60
DEFAULT_STALE_MINUTES = 30
DEFAULT_BOX_OFFLINE_MINUTES = 15
DEFAULT_RESTORE_AFTER_RECONNECT = True
MIN_BOX_OFFLINE_MINUTES = 5
MAX_BOX_OFFLINE_MINUTES = 120
DEFAULT_VACATION_DAYS = 30
MIN_VACATION_DAYS = 1
MAX_VACATION_DAYS = 365
DEFAULT_FILTER_MONTHS = 9
MIN_FILTER_MONTHS = 1
MAX_FILTER_MONTHS = 24
DAYS_PER_FILTER_MONTH = 30
# Il reset dal display riporta ff_cpt (usura %) a 0: lo rilevo se scende di almeno 5 punti
FILTER_RESET_DROP = 5
HISTORY_PAGE_SIZE = 500
HISTORY_MAX_PAGES = 60

MIN_SCAN_INTERVAL = 60
MAX_SCAN_INTERVAL = 900
MIN_KITCHEN_MINUTES = 1
MAX_KITCHEN_MINUTES = 240
MIN_BOOST_MINUTES = 1
MAX_BOOST_MINUTES = 720

# Codici modalita' della Box -> nome mostrato
# Livelli: L0 Vacanza (W), L1 Quotidiano (V), L2 Cucina (Y), L3 Boost (X).
# Le portate e le durate le imposta l'installatore; l'app Aldes puo' usare nomi diversi.
MODE_VACATION = "W"
MODE_DAILY = "V"
MODE_KITCHEN = "Y"
MODE_BOOST = "X"
MODE_NAMES: dict[str, str] = {
    "V": "Quotidiano",
    "Y": "Cucina",
    "X": "Boost",
    "Z": "Programma aria",
    "W": "Vacanze",
}

OPTION_VACATION = "Vacanza"
OPTION_DAILY = "Quotidiano"
OPTION_KITCHEN = "Cucina"
OPTION_BOOST = "Boost"
SELECT_OPTIONS = [OPTION_VACATION, OPTION_DAILY, OPTION_KITCHEN, OPTION_BOOST]

# Tempo massimo in cui il select mostra la modalita' richiesta in attesa di conferma
PENDING_TIMEOUT = 20 * 60
# Affidabilita' dei comandi: pausa minima tra due invii, attesa della conferma, un solo nuovo invio
COMMAND_MIN_INTERVAL = 30
COMMAND_VERIFY_TIMEOUT = 90
# Dopo quanto tempo dall'avvio del Boost un dato con altra modalita' lo annulla
BOOST_EXTERNAL_CHANGE_GRACE = 120

# Dopo una lettura fallita (bridge irraggiungibile): nuovi tentativi ogni 30 s per al massimo 10 minuti,
# poi si torna al ciclo normale (scan_interval). Nessuna tempesta di richieste.
BRIDGE_RETRY_SECONDS = 30
BRIDGE_RETRY_WINDOW = 600

# Rientro automatico (Cucina/Boost) non inviato perche' la Box e' scollegata: si riprova al ritorno
PENDING_RETURN_MAX_AGE = 12 * 3600
PENDING_RETURN_MAX_REJECTS = 3
ISSUE_BOX_OFFLINE = "box_offline"
ISSUE_RESTORE_FAILED = "restore_failed"
# "Nessun messaggio": la Box ne manda uno ogni ~10 minuti e di notte del 4-5/11/2026 ci sono stati buchi di
# 19 e 28 minuti con la rete della Box instabile. Costante interna (non e' un'opzione): vale
# max(box_offline_minutes, MIN_SILENCE_MINUTES) per la Riparazione "Box scollegata" da silenzio.
MIN_SILENCE_MINUTES = 30
# Ripristino dopo una riconnessione: messaggi consecutivi richiesti prima di decidere
RESTORE_STABLE_MESSAGES = 2

SERVICE_SEND_COMMAND = "send_command"
STORAGE_VERSION = 1
