# Aldes VMC (locale)

Versione / Version **0.2.0**

🇮🇹 [Italiano](#italiano) · 🇬🇧 [English](#english)

> Progetto **non ufficiale**, indipendente da Aldes. / **Unofficial** project, not affiliated with Aldes.

---

## Italiano

Integrazione per Home Assistant che controlla in locale la VMC **Aldes InspirAIR Home S**, quando il cloud Aldes non è più disponibile. Legge e comanda la VMC tramite l'app **Aldes Bridge** di [saniho](https://github.com/saniho/aldes-bridge) (licenza MIT): questa integrazione non contiene codice del bridge e usa solo le sue API HTTP.

[Guida completa passo passo (PDF)](Guida_Aldes_VMC_in_locale.pdf)


### Architettura
```
VMC ── AldesConnect Box ──(DNS: aldesiotsuite.azure-devices.net → IP di Home Assistant)──▶ Aldes Bridge (porta 8080)
                                                                                              ▲
                                                                       Home Assistant · aldes_vmc (HTTP, polling)
```
La Box invia i dati circa ogni **10 minuti**; l'integrazione legge l'ultimo dato dallo storico del bridge (sopravvive ai riavvii del bridge).

### Requisiti
- Home Assistant 2025.1 o successivo
- App/add-on **Aldes Bridge** funzionante e raggiungibile (default porta 8080)
- La Box deve risolvere il nome del cloud Aldes verso il bridge (vedi sotto)

### Installazione (HACS, repository personalizzato)
1. HACS → ⋮ → *Repository personalizzati* → incolla `https://github.com/Conedo95/aldes_vmc`, categoria **Integrazione**.
2. Installa **Aldes VMC (locale)** e riavvia Home Assistant.
3. *Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Aldes VMC (locale)*: indirizzo e porta del bridge (per esempio `192.168.1.x` e `8080`, di solito l'IP di Home Assistant).

Installazione manuale: copia `custom_components/aldes_vmc` in `/config/custom_components/` e riavvia.

### DNS (Pi-hole e FRITZ!Box)
La Box contatta `aldesiotsuite.azure-devices.net`: deve risolverlo con l'IP di Home Assistant.
- **Pi-hole**: *Local DNS Records* → dominio `aldesiotsuite.azure-devices.net` → IP di Home Assistant.
- **FRITZ!Box**: se i nomi che puntano a IP locali vengono bloccati (protezione *DNS rebind*), aggiungi il dominio alle eccezioni: *Rete domestica → Rete → Impostazioni di rete → Protezione da rebinding DNS*. Se usi Pi-hole come DNS del FRITZ!Box, aggiungi l'eccezione lì.
- Il bridge deve avere il redirect della porta 8883 (vedi la documentazione del bridge). Il test `GET /api/diagnostic` del bridge indica cosa manca.

### Configurazione e opzioni
Setup: indirizzo e porta del bridge. Opzioni: intervallo di aggiornamento (60–900 s, default 300), **durata di Cucina** (1–240 min, default 30), **durata del Boost** (1–720 min, default 60), **durata filtri** (1–24 mesi, default 9 = 270 giorni), **giorni di Vacanza** (1–365, default 30; la Vacanza non ha un timer, la data di fine è solo di sicurezza), tolleranza dati obsoleti (default 30 min).

### Entità
| Entità | Dato |
|---|---|
| `sensor.vmc_aldes_temperatura_esterna` | aria esterna (`outside_tpt`) |
| `sensor.vmc_aldes_temperatura_estratta` | aria estratta (`ext_tpt`) |
| `sensor.vmc_aldes_temperatura_reimmessa` | aria reimmessa dopo lo scambiatore (nel bridge il campo si chiama `reject_tpt`, ma corrisponde all'aria immessa) |
| `sensor.vmc_aldes_portata_immissione` / `_estrazione` | m³/h |
| `sensor.vmc_aldes_giri_ventilatore_immissione` / `_estrazione` | giri/min |
| `sensor.vmc_aldes_velocita_impostata` | velocità impostata |
| `sensor.vmc_aldes_contatore_filtri` | **Usura filtri** in % (`ff_cpt`, troncata; 0 = filtri nuovi) |
| `sensor.vmc_aldes_giorni_filtri_rimanenti` | **Giorni filtri rimanenti** = durata filtri − giorni dall'ultimo reset. Attributi: `data_ultimo_reset`, `giorni_trascorsi`, `durata_giorni`, `usura_calcolata_percentuale` |
| `sensor.vmc_aldes_indicatore_depressione` | **da verificare** |
| `sensor.vmc_aldes_modalita_attuale` | Vacanze / Quotidiano / Cucina / Boost / Programma aria (mantiene l'ultimo valore noto) |
| `sensor.vmc_aldes_ultimo_dato`, `sensor.vmc_aldes_fine_cucina`, `sensor.vmc_aldes_fine_boost` | diagnostica / fine di Cucina / fine del Boost |
| `binary_sensor.vmc_aldes_connessione` | Box e bridge collegati |
| `select.vmc_aldes_modalita` | **Vacanza** / **Quotidiano** / **Cucina** / **Boost** |
| `button.vmc_aldes_aggiorna` | rilegge subito il bridge (non invia nulla alla Box) |

Disattivati di default (diagnostica): DTB, scambiatore, consegne, CO₂, PM2.5, VOC.
Servizio avanzato `aldes_vmc.send_command` (`method`, `params`) per prove.

### Modalità (livelli di portata)
| Opzione | Codice `changeMode` | Livello | Portata | Durata predefinita |
|---|---|---|---|---|
| **Vacanza** | `W` + date | L0 | 45 m³/h (nella nostra installazione) | nessun rientro (data di fine di sicurezza: 30 giorni) |
| **Quotidiano** | `V` | L1 | 70 m³/h | — |
| **Cucina** | `Y` | L2 | 100 m³/h | 30 minuti, poi rientro a Quotidiano |
| **Boost** | `X` | L3 | 120 m³/h | 60 minuti, poi rientro a Quotidiano |

Portate e durate le imposta l'installatore (menu installatore della macchina): i valori in tabella sono quelli della nostra installazione e possono essere diversi nella tua. L'app Aldes può usare nomi diversi per gli stessi livelli. Le durate di Cucina e Boost sono opzioni dell'integrazione.

Cucina e Boost hanno un timer che sopravvive al riavvio di Home Assistant: alla scadenza l'integrazione riporta la VMC a **Quotidiano** (subito, se la scadenza è passata durante lo spegnimento). Se la modalità viene cambiata altrove (dato successivo diverso), il timer si annulla. "Comando inviato" significa che il bridge ha inoltrato il messaggio; la Box lo conferma nel dato successivo (di solito entro pochi secondi; il select mostra la modalità richiesta come "in attesa di conferma"). Se la Box non è collegata al bridge il comando viene rifiutato con un messaggio chiaro e non è messo in coda.

### Affidabilità dei comandi
Tra due comandi alla Box passano almeno 30 secondi (quelli ravvicinati restano in attesa, non si perdono). Dopo ogni cambio di modalità, anche il rientro automatico di Cucina/Boost, l'integrazione verifica entro 90 secondi che la Box l'abbia eseguito; se no, lo reinvia **una sola volta**. Se fallisce di nuovo scrive un avviso nel log e valorizza l'attributo `ultimo_errore_comando` del selettore, senza altri tentativi.

### Vacanza
Scegliendo **Vacanza** la VMC passa in modalità Vacanza (codice `W`) e gli eventuali timer di Cucina e Boost vengono annullati. Il comando è `changeMode` con **una sola stringa** `"W" + inizio + fine`, date in UTC nel formato `YYYYMMDDHHMMSS` seguite da `Z`, senza punto: per esempio `["W20300101120000Z20300131120000Z"]`. L'inizio è "adesso", la fine è "adesso + giorni di Vacanza" (opzione, default 30).
**La Vacanza non ha un timer di rientro**: la data di fine è fittizia e serve solo da sicurezza. Per tornare a Quotidiano scegli **Quotidiano** dal selettore o da un'automazione. La Box non restituisce le date di inizio/fine (restano vuote). Con la Vacanza la velocità impostata scende a 0 e portate e giri calano leggermente.

Esempio di automazione:
```yaml
action: select.select_option
target:
  entity_id: select.vmc_aldes_modalita
data:
  option: Vacanza   # oppure: Quotidiano
```

### Limiti noti
- Il **reset dei filtri si esegue dal display** della macchina; l'integrazione lo rileva da sola (`ff_cpt` scende di almeno 5 punti o va a 0) e salva la data del messaggio della Box. Al primo avvio la data si cerca nello storico del bridge (ultima transizione verso 0); se manca, si stima da `ff_cpt`.
- Il significato di `dep_ind` (indicatore depressione) resta da verificare.
- Dati ogni ~10 minuti; dipendenza dal bridge e dal DNS.
- Il bridge non ha un'API documentata ufficialmente: potrebbero esserci cambiamenti tra versioni (testato con la 0.20.0).

### Aggiornamento dalla 0.1.0
- **Attenzione:** nella 0.1.0 l'opzione **Boost** era il livello a 100 m³/h; ora quel livello si chiama **Cucina** e **Boost** è il nuovo livello 3 (120 m³/h). Automazioni, script e plance che chiamavano `select.select_option` con `option: Boost` vanno cambiati in `Cucina` per avere lo stesso comportamento di prima.
- La migrazione è automatica: la durata del vecchio Boost diventa la durata di Cucina; il sensore "Fine Boost" diventa "Fine Cucina" (stessa entità, stessa cronologia, nuovo `entity_id` `sensor.vmc_aldes_fine_cucina` se non l'avevi personalizzato); un eventuale timer in corso continua come Cucina. Il nuovo "Fine Boost" e i sensori dei filtri sono creati da zero.
- `sensor.vmc_aldes_contatore_filtri` ora ha l'unità `%`: se Home Assistant segnala un cambio di unità tra le Riparazioni, scegli di aggiornare le statistiche.

### Disinstallazione / ritorno indietro
Dispositivi e servizi → Aldes VMC (locale) → ⋮ → *Elimina* (rimuove anche i file dei timer salvati); poi rimuovi `custom_components/aldes_vmc` (o disinstalla da HACS) e riavvia. Il bridge non viene toccato.

### Crediti
[saniho/aldes-bridge](https://github.com/saniho/aldes-bridge) (MIT) per il bridge; in precedenza i lavori di avilleret e Smeagolworms4 per il Modbus hanno ispirato la ricerca. Aldes e InspirAIR sono marchi dei rispettivi proprietari.

---

## English

Home Assistant integration for local control of the **Aldes InspirAIR Home S** ventilation unit (VMC/MVHR) when the Aldes cloud is unavailable. It talks to the **Aldes Bridge** app by [saniho](https://github.com/saniho/aldes-bridge) (MIT) over its HTTP API only; no bridge code is included.

[Step-by-step guide (PDF, Italian)](Guida_Aldes_VMC_in_locale.pdf)


**Install:** HACS → Custom repositories → add `https://github.com/Conedo95/aldes_vmc` as *Integration* → install → restart → add *Aldes VMC (locale)* and enter the bridge host/port (default `8080`).
**DNS:** the Box must resolve `aldesiotsuite.azure-devices.net` to the Home Assistant IP (Pi-hole *Local DNS Records*; on a FRITZ!Box add the domain to the DNS-rebind exceptions).
**Options:** update interval (60–900 s), **Kitchen duration** (default 30 min), **Boost duration** (default 60 min), **vacation days** (1–365, default 30; end date is only a safety limit), **filter life** (1–24 months, default 9 = 270 days), stale-data tolerance.
**Entities:** temperatures (outdoor, extract, re-injected supply air after the exchanger — the bridge field is called `reject_tpt` but it is the supplied air), supply/extract flow (m³/h), fan speeds, set speed, filter wear % and *days remaining* (from the last reset) and pressure indicator (*to be verified*), current mode (last known value kept), connection, `select` **Holiday (Vacanza) / Daily / Kitchen (Cucina) / Boost**, refresh button, `aldes_vmc.send_command` service.
**Modes (flow levels):**

| Option | `changeMode` code | Level | Flow | Default duration |
|---|---|---|---|---|
| **Vacanza** (Holiday) | `W` + dates | L0 | 45 m³/h (our installation) | no return (safety end date: 30 days) |
| **Quotidiano** (Daily) | `V` | L1 | 70 m³/h | — |
| **Cucina** (Kitchen) | `Y` | L2 | 100 m³/h | 30 minutes, then back to Daily |
| **Boost** | `X` | L3 | 120 m³/h | 60 minutes, then back to Daily |

Flows and durations are set by the installer (installer menu of the unit): the table shows our installation and yours may differ. The Aldes app may use different names for the same levels. Kitchen and Boost have a persistent timer (survives restarts); the durations are integration options. If the Box is not connected to the bridge the command is rejected with a clear message and is not queued.
**Known limits:** the filter reset is done on the machine display and the integration detects it by itself (wear counter drops by ≥5 points or goes to 0; date taken from the Box message); data every ~10 min; depends on the bridge and DNS.
**Command reliability:** at least 30 s between two commands to the Box (close ones wait, they are not dropped). After every mode change, also the automatic return from Kitchen/Boost, the integration checks within 90 s that the Box executed it; if not, it resends it **once**. If that fails too it logs a warning and sets the select attribute `ultimo_errore_comando`, with no further retries.
**Holiday:** choosing *Vacanza* sends `changeMode` with one string `"W"+start+end` (UTC `YYYYMMDDHHMMSSZ`, no dot). There is no return timer; the end date (now + vacation days) is only a safety limit. Go back with *Quotidiano*. Automation: `select.select_option` with `option: Vacanza`/`Quotidiano`.
**Upgrading from 0.1.0:** the old **Boost** option (100 m³/h) is now called **Cucina** (Kitchen) and **Boost** is the new level 3 (120 m³/h): change automations, scripts and dashboards that used `option: Boost` to `Cucina` to keep the old behaviour. Migration is automatic (old Boost duration → Kitchen duration; the "Boost end" sensor becomes "Kitchen end", same entity and history, a running timer continues as Kitchen). The filter counter now has the unit `%`: if Home Assistant shows a unit-change repair, choose to update the statistics.
**Uninstall:** delete the integration entry, remove `custom_components/aldes_vmc`, restart.
**Credits:** Aldes Bridge by saniho (MIT). Not affiliated with Aldes.
