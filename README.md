# Aldes VMC (locale)

🇮🇹 [Italiano](#italiano) · 🇬🇧 [English](#english)

> Progetto **non ufficiale**, indipendente da Aldes. / **Unofficial** project, not affiliated with Aldes.

---

## Italiano

Integrazione per Home Assistant che controlla in locale la VMC **Aldes InspirAIR Home S**, quando il cloud Aldes non è più disponibile. Legge e comanda la VMC tramite l'app **Aldes Bridge** di [saniho](https://github.com/saniho/aldes-bridge) (licenza MIT): questa integrazione non contiene codice del bridge e usa solo le sue API HTTP.

### Architettura
```
VMC ── AldesConnect Box ──(DNS: aldesiotsuite.azure-devices.net → IP di Home Assistant)──▶ Aldes Bridge (porta 8080)
                                                                                              ▲
                                                                       Home Assistant · aldes_vmc (HTTP, polling)
```
La Box invia i dati circa ogni **10 minuti**; l'integrazione legge l'ultimo dato dallo storico del bridge (sopravvive ai riavvii del bridge).

### Requisiti
- Home Assistant 2025.1 o successivo
- App/add-on **Aldes Bridge** ([saniho/aldes-bridge](https://github.com/saniho/aldes-bridge)) installata, funzionante e raggiungibile (default porta 8080); per l'installazione segui il suo README
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
Setup: indirizzo e porta del bridge. Opzioni: intervallo di aggiornamento (60–900 s, default 300), **durata del Boost** (1–240 min, default 30), tolleranza dati obsoleti (default 30 min).

### Entità
| Entità | Dato |
|---|---|
| `sensor.vmc_aldes_temperatura_esterna` | aria esterna (`outside_tpt`) |
| `sensor.vmc_aldes_temperatura_estratta` | aria estratta (`ext_tpt`) |
| `sensor.vmc_aldes_temperatura_reimmessa` | aria reimmessa in ambiente (nel bridge il campo si chiama `reject_tpt`) |
| `sensor.vmc_aldes_portata_immissione` / `_estrazione` | m³/h |
| `sensor.vmc_aldes_giri_ventilatore_immissione` / `_estrazione` | giri/min |
| `sensor.vmc_aldes_velocita_impostata` | velocità impostata |
| `sensor.vmc_aldes_contatore_filtri` | **da verificare** (probabilmente giorni) |
| `sensor.vmc_aldes_indicatore_depressione` | **da verificare** |
| `sensor.vmc_aldes_modalita_attuale` | Quotidiano / Boost / Programma aria / Vacanze (mantiene l'ultimo valore noto) |
| `sensor.vmc_aldes_ultimo_dato`, `sensor.vmc_aldes_fine_boost` | diagnostica / fine del Boost |
| `binary_sensor.vmc_aldes_connessione` | Box e bridge collegati |
| `select.vmc_aldes_modalita` | **Quotidiano** / **Boost** |
| `button.vmc_aldes_aggiorna` | rilegge subito il bridge (non invia nulla alla Box) |

Gli ID entità qui sopra valgono con Home Assistant in italiano: in altre lingue i nomi (e quindi gli ID generati) seguono la traduzione, ad esempio `sensor.vmc_aldes_outdoor_temperature`.

Disattivati di default (diagnostica): DTB, scambiatore, consegne, CO₂, PM2.5, VOC.
Servizio avanzato `aldes_vmc.send_command` (`method`, `params`) per prove: **non usare per Vacanza**.

### Boost
Scegliendo **Boost** la VMC passa a Boost e, dopo la durata impostata, l'integrazione la riporta a **Quotidiano**. La fine è salvata su disco: se Home Assistant si riavvia durante il Boost, il rientro riparte (o avviene subito se la scadenza è passata). Se la modalità viene cambiata altrove (dato successivo ≠ Boost), il timer si annulla.
Nota: "comando inviato" significa che il bridge ha inoltrato il messaggio; la Box lo conferma nel dato successivo (il select mostra la modalità richiesta come "in attesa di conferma").

### Limiti noti
- **Vacanza** non supportata (il comando non funziona).
- Reset filtri non disponibile (comando sconosciuto); significato di contatore filtri e depressione da verificare.
- Dati ogni ~10 minuti; dipendenza dal bridge e dal DNS.
- Il bridge non ha un'API documentata ufficialmente: potrebbero esserci cambiamenti tra versioni (testato con la 0.20.0).

### Disinstallazione / ritorno indietro
Dispositivi e servizi → Aldes VMC (locale) → ⋮ → *Elimina* (rimuove anche il file del Boost salvato); poi rimuovi `custom_components/aldes_vmc` (o disinstalla da HACS) e riavvia. Il bridge non viene toccato.

### Crediti
[saniho/aldes-bridge](https://github.com/saniho/aldes-bridge) (MIT) per il bridge. Aldes e InspirAIR sono marchi dei rispettivi proprietari.

---

## English

Home Assistant integration for local control of the **Aldes InspirAIR Home S** ventilation unit (VMC/MVHR) when the Aldes cloud is unavailable. It talks to the **Aldes Bridge** app by [saniho](https://github.com/saniho/aldes-bridge) (MIT) over its HTTP API only; no bridge code is included.

**Install:** HACS → Custom repositories → add `https://github.com/Conedo95/aldes_vmc` as *Integration* → install → restart → add *Aldes VMC (locale)* and enter the bridge host/port (default `8080`).
**DNS:** the Box must resolve `aldesiotsuite.azure-devices.net` to the Home Assistant IP (Pi-hole *Local DNS Records*; on a FRITZ!Box add the domain to the DNS-rebind exceptions).
**Options:** update interval (60–900 s), **Boost duration** (default 30 min), stale-data tolerance.
**Entities:** temperatures (outdoor, extract, supply air re-injected into the rooms — the bridge field is called `reject_tpt`), supply/extract flow (m³/h), fan speeds, set speed, filter counter and pressure indicator (*to be verified*), current mode (last known value kept), connection, `select` **Daily / Boost**, refresh button, `aldes_vmc.send_command` service.
**Boost:** returns to Daily after the configured time; the end time is stored and survives Home Assistant restarts.
**Known limits:** Holiday mode not supported; filter reset unknown; data every ~10 min; depends on the bridge and DNS.
**Uninstall:** delete the integration entry, remove `custom_components/aldes_vmc`, restart.
**Credits:** Aldes Bridge by saniho (MIT). Not affiliated with Aldes.
