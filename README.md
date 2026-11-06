# Aldes VMC (locale)

Versione / Version **0.2.1**

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

> **Nota (Home Assistant 2026.11):** con Home Assistant 2026.11 HACS è stato sostituito dal Marketplace. I passaggi HACS qui sopra descrivono HACS e potrebbero non corrispondere a quello che vedi: l'installazione manuale in `custom_components` resta valida.

### DNS (Pi-hole e FRITZ!Box)
La Box contatta `aldesiotsuite.azure-devices.net`: deve risolverlo con l'IP di Home Assistant.
- **Pi-hole**: *Local DNS Records* → dominio `aldesiotsuite.azure-devices.net` → IP di Home Assistant.
- **FRITZ!Box**: se i nomi che puntano a IP locali vengono bloccati (protezione *DNS rebind*), aggiungi il dominio alle eccezioni: *Rete domestica → Rete → Impostazioni di rete → Protezione da rebinding DNS*. Se usi Pi-hole come DNS del FRITZ!Box, aggiungi l'eccezione lì.
- Il bridge deve avere il redirect della porta 8883 (vedi la documentazione del bridge). Il test `GET /api/diagnostic` del bridge indica cosa manca.

### Configurazione e opzioni
Setup: indirizzo e porta del bridge. Opzioni: intervallo di aggiornamento (60–900 s, default 300), **durata di Cucina** (1–240 min, default 30), **durata del Boost** (1–720 min, default 60), **durata filtri** (1–24 mesi, default 9 = 270 giorni), **giorni di Vacanza** (1–365, default 30; la Vacanza non ha un timer, la data di fine è solo di sicurezza), tolleranza dati obsoleti (default 30 min), **Box considerata scollegata dopo** (`box_offline_minutes`, 5–120 min, default 15: dopo questo tempo compare la Riparazione) e **Ripristina la modalità dopo una riconnessione** (default attivo).

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

### Box scollegata, dati non aggiornati e ripristino (v0.2.1)
**Riparazione "Box scollegata".** Se la Box (o il bridge) resta scollegata oltre `box_offline_minutes` (default 15, 5–120), oppure è collegata ma non manda messaggi da oltre `max(box_offline_minutes, 30)` minuti (la Box ne manda uno ogni ~10 e con la rete instabile può avere buchi di 20–30 minuti: **30 è una costante interna** dell'integrazione, non un'opzione; `box_offline_minutes` resta 15 per la Riparazione da scollegamento e per il ripristino), compare un avviso in *Impostazioni → Riparazioni* (gravità "avviso", non risolvibile da lì) con la procedura. Si chiude da sola quando la Box torna collegata e manda un messaggio. Nessuna notifica sul telefono e nessuna automazione: è solo l'avviso interno. **Anti-rimbalzo:** una caduta più breve della soglia non apre nulla e non fa scattare il ripristino generale. Dopo un riavvio di Home Assistant il conteggio dei minuti riparte da zero.

**`dati_non_aggiornati`.** Attributo (bool) del selettore e di tutti i sensori, compreso `ultimo_dato`: vero se l'ultimo dato è più vecchio di "dati obsoleti dopo" (default 30 min) oppure la Box è scollegata da almeno `box_offline_minutes`. Il selettore **mantiene l'ultima modalità nota** (non diventa `unknown`, così le automazioni che lo controllano possono scattare); `sensor.vmc_aldes_modalita_attuale` diventa `unknown` con l'ultima modalità nota in `ultima_modalita_nota`. Le plance non evidenziano il tasto della modalità se la connessione è `off` o il dato è obsoleto.

**Bridge irraggiungibile (aggiornamenti e riavvii dell'app).** Dopo una lettura fallita l'integrazione riprova ogni **30 secondi per al massimo 10 minuti**, poi torna al ciclo normale (`scan_interval`): nessuna tempesta di richieste. Le entità **non diventano "non disponibili"**: selettore e sensori mantengono l'ultimo valore (il sensore di connessione resta com'era finché l'assenza non è confermata). Vale la stessa regola della Box scollegata: sotto `box_offline_minutes` (15) `dati_non_aggiornati` resta falso e non compare nessuna Riparazione; oltre la soglia `dati_non_aggiornati` diventa vero, il sensore *Modalità attuale* diventa `unknown`, il sensore di connessione si spegne e compare la Riparazione. Un comando dato in quel periodo viene rifiutato (non messo in coda) e, se è Quotidiano o Vacanza, aggiorna l'obiettivo e viene consegnato al ritorno. Le entità sono "non disponibili" solo se non c'è mai stato nessun dato (primo avvio con il bridge fermo). Il 5/11/2026, con la 0.2.0, durante un aggiornamento del bridge (fermo ~10 s) tutte le entità erano rimaste non disponibili per 5 minuti (fino alla lettura successiva da 300 s) e le automazioni basate sul selettore sarebbero saltate. Con un bridge fermo oltre la soglia, al ritorno vale il ripristino (2 messaggi consecutivi).

**Comandi con la Box scollegata** vengono rifiutati subito con un errore chiaro e non vengono messi in coda. Fanno eccezione solo **Quotidiano e Vacanza**: la modalità richiesta (e l'istante) aggiorna comunque lo *stato obiettivo* salvato, che viene consegnato al ritorno della Box (anche dopo un'assenza breve, vedi sotto). Cucina e Boost rifiutati **non vengono mai consegnati**: non cambiano l'obiettivo e non vengono recuperati. L'attributo `obiettivo_non_consegnato` del selettore dice se c'è un comando in attesa.

**Rientro programmato (Cucina/Boost → Quotidiano).** Il timer è salvato su disco. Se la scadenza arriva con la Box scollegata il rientro resta in sospeso fino a **12 ore** dalla scadenza, poi si rinuncia e si scrive nel log. Al ritorno si attende un messaggio **nuovo**: se la Box dichiara ancora la modalità del timer **o già Quotidiano** si invia un solo `V` (vedi "sblocco"); se dichiara un'altra modalità (per esempio cambiata dal display) il pendente si annulla senza comandi, con una riga nel log. 30 s minimi tra comandi e verifica a 90 s con un solo rinvio, come sempre.

**Ripristino dopo una riconnessione** (opzione *Ripristina la modalità dopo una riconnessione*, default attiva). L'integrazione salva l'ultimo *stato obiettivo* (modalità, istante del comando, scadenza del timer, date di Vacanza). Solo al passaggio offline → online, e solo se l'assenza è stata di almeno `box_offline_minutes` (oppure c'è un comando Quotidiano/Vacanza rifiutato non consegnato), attende **2 messaggi consecutivi** della Box (con la cadenza reale sono circa 10–20 minuti dopo il ritorno; una nuova caduta azzera il conteggio) e poi invia **un solo comando**:

| Obiettivo salvato | Comando |
|---|---|
| Quotidiano | `V` |
| Vacanza con data di fine non trascorsa | `W` con la data di fine salvata |
| Vacanza con data di fine trascorsa | `V` |
| Cucina o Boost con timer scaduto | `V` (annullato senza comandi se la Box dichiara un'altra modalità) |
| Cucina o Boost con timer ancora valido | nessun invio |

*Sblocco:* il comando si invia **anche se la Box dichiara già quella modalità**. Il 4/11/2026, dopo un blackout, la Box dichiarava Quotidiano (`V`, `set_spd` 1) mentre i ventilatori giravano ancora a livello Cucina (100 m³/h, circa 2450 giri, `dep_ind` 41): un solo `V` ha riportato tutto a 70 m³/h in circa 6 minuti. **Attenzione: la conferma verifica solo che la Box riporti la modalità in un messaggio nuovo; non accerta l'effetto fisico sulla macchina.** Se la conferma non arriva entro 90 s c'è un solo rinvio; se fallisce anche quello si apre la Riparazione "Ripristino non riuscito" e ci si ferma. Quando e perché è scattato un ripristino è nel log e nell'attributo `ultimo_ripristino` del selettore. Nessun ripristino ai normali riavvii di Home Assistant con la Box collegata. I cambi di modalità fatti dal display diventano il nuovo obiettivo **solo con la Box stabile** (dopo almeno 2 messaggi consecutivi senza cadute e 120 s dall'ultimo comando); la modalità dichiarata nei primi messaggi dopo una riconnessione non viene mai adottata. Una Vacanza, una Cucina o un Boost impostati dal display, di cui non si conosce la scadenza, non vengono ripristinati.

**Limite noto:** se Home Assistant è spento alle 09:00 (o nel momento in cui deve scattare un'automazione), l'automazione **non gira in ritardo**: l'integrazione non conosce le automazioni. Se la VMC era in Vacanza per la notte e Home Assistant era spento alle 09:00, al ritorno l'ultimo obiettivo salvato resta Vacanza e viene ripristinato (finché la data di fine, 30 giorni dopo la richiesta, non è trascorsa): in quel caso riporta la VMC a Quotidiano dal selettore.

**Rischio noto:** un cambio di modalità fatto dal **display durante l'assenza** della Box (o dichiarato dalla Box dopo un blackout) viene annullato al ritorno, perché si ripristina l'ultimo obiettivo. Per non avere ripristini, disattiva l'opzione.

**Procedura "Box scollegata dopo un blackout".** (1) Aspetta qualche minuto: la Box si ricollega da sola alla rete. (2) Se la Riparazione compare o la Box non torna: togli corrente alla VMC dal magnetotermico per 15–20 secondi, ridai corrente e attendi circa 5 minuti. (3) Controlla sul display la modalità reale. (4) Se la Box non torna comunque, verifica che l'app Aldes Bridge sia in esecuzione e che il nome DNS della Box punti a Home Assistant. (5) Al ritorno, il ripristino automatico (se serve) parte dopo 2 messaggi consecutivi.

**Correzione:** il nuovo tentativo di rientro non va più in errore (`hass.async_create_task` chiamato da un thread, visto il 04/11/2026): ora gira nel loop di Home Assistant.

**Correzione (avvio con il bridge in ritardo):** se la prima lettura del bridge fallisce all'avvio (bridge non ancora pronto), Home Assistant ritenta l'avvio dell'integrazione ma non scarica il tentativo fallito: il suo timer di 15 minuti restava attivo e apriva una Riparazione "Box scollegata" falsa (visto il 05/11/2026 alle 19:05, dopo il riavvio del dispositivo). Ora un avvio fallito ferma i suoi timer e un monitor scaricato non apre più nulla.

### Limiti noti
- Il **reset dei filtri si esegue dal display** della macchina; l'integrazione lo rileva da sola (`ff_cpt` scende di almeno 5 punti o va a 0) e salva la data del messaggio della Box. Al primo avvio la data si cerca nello storico del bridge (ultima transizione verso 0); se manca, si stima da `ff_cpt`.
- Il significato di `dep_ind` (indicatore depressione) resta da verificare.
- Dati ogni ~10 minuti; dipendenza dal bridge e dal DNS.
- Il bridge non ha un'API documentata ufficialmente: potrebbero esserci cambiamenti tra versioni (testato con la 0.20.0).

### Aggiornamento dalla 0.2.0
- **Fai prima un backup** di Home Assistant (o almeno della cartella `custom_components/aldes_vmc`).
- Sostituisci i file dell'integrazione (oppure aggiorna dal gestore che usi), poi **riavvia Home Assistant**: ricaricare l'integrazione non basta, perché i file Python già caricati restano in memoria e le modifiche non vengono lette.
- Le opzioni e le entità esistenti restano; le due opzioni nuove (`box_offline_minutes` e il ripristino dopo una riconnessione) prendono il valore predefinito.
- File aggiunti rispetto alla 0.2.0: `connection.py` e `restore.py`. Il file `boost.py` della 0.2.0 non è più presente: se rimane nella cartella, eliminalo.

### Aggiornamento dalla 0.1.0
- Per la 0.1.0 valgono anche le indicazioni sul backup e sul riavvio della sezione "Aggiornamento dalla 0.2.0".
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
**Note (Home Assistant 2026.11):** with Home Assistant 2026.11 HACS has been replaced by the Marketplace. The HACS steps above describe HACS and may not match what you see; manual installation in `custom_components` remains valid.
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
**Upgrading from 0.2.0:** make a backup first (Home Assistant, or at least the `custom_components/aldes_vmc` folder). After replacing the files (or updating with the tool you use), **restart Home Assistant**: reloading the integration is not enough, because Python files already loaded stay in memory and changes are not read. Existing options and entities are kept; the two new options (`box_offline_minutes` and restore after reconnection) take their default values. New files compared with 0.2.0: `connection.py` and `restore.py`; `boost.py` from 0.2.0 is no longer present, delete it if it stays in the folder. The backup and restart advice also applies when upgrading from 0.1.0.
**Upgrading from 0.1.0:** the old **Boost** option (100 m³/h) is now called **Cucina** (Kitchen) and **Boost** is the new level 3 (120 m³/h): change automations, scripts and dashboards that used `option: Boost` to `Cucina` to keep the old behaviour. Migration is automatic (old Boost duration → Kitchen duration; the "Boost end" sensor becomes "Kitchen end", same entity and history, a running timer continues as Kitchen). The filter counter now has the unit `%`: if Home Assistant shows a unit-change repair, choose to update the statistics.
**Box offline, stale data and restore (v0.2.1):** a Repair "Box disconnected" (warning, not fixable) opens when the Box/bridge stays disconnected longer than `box_offline_minutes` (default 15, 5–120) or is connected but silent for more than `max(box_offline_minutes, 30)` minutes (30 is an internal constant, not an option; `box_offline_minutes` stays 15 for the disconnection Repair and for the restore); it closes by itself when the Box is back. No phone notification, no automation. Drops shorter than the threshold open nothing and trigger no restore. The selector and all sensors expose `dati_non_aggiornati`; the selector keeps the last known mode (automations keep working), the *Current mode* sensor becomes `unknown`. Commands are refused immediately while the Box is offline (never queued) — except Daily and Holiday, which still update the persisted *goal state* and are delivered when the Box returns (Kitchen/Boost refused are dropped). A Kitchen/Boost return that falls due offline stays pending for up to 12 hours; after a new Box message it is sent if the Box reports the timer's mode or already Daily, and dropped without commands if it reports another mode. **Restore after reconnection** (option, default on): after an absence of at least `box_offline_minutes` (or an undelivered Daily/Holiday command) the integration waits for 2 consecutive Box messages (roughly 10–20 minutes) and sends ONE command: Daily→`V`; Holiday→`W` with the stored end date (or `V` if expired); Kitchen/Boost with an expired timer→`V`; with a valid timer nothing. It is sent **even if the Box already reports that mode** (unlock: on 4 Nov 2026 the Box reported `V` while the fans still ran at Kitchen level). The confirmation only checks that the Box reports the mode in a new message; **it does not prove the physical effect**. One resend after 90 s; if that also fails a Repair "Mode restore failed" opens and it stops. Risk: a mode changed from the display during the absence is undone on return. Procedure after a blackout: wait a few minutes; if needed cut power to the VMC at the circuit breaker for 15–20 s, restore and wait ~5 min. Bridge unreachable (add-on updates/restarts): after a failed read it retries every 30 s for at most 10 minutes, then goes back to the normal cycle; entities never become unavailable (they keep the last value; with the same debounce as the Box: below `box_offline_minutes` `dati_non_aggiornati` stays false and no Repair, beyond it the flag is true and the Repair opens); a command in that period is refused and, if Daily/Holiday, updates the goal and is delivered on return. Entities are unavailable only if there has never been data. Fixed: the retry no longer raises `hass.async_create_task` from a thread. Fixed: a failed first start (bridge not ready yet) no longer leaves a 15-minute timer behind that opened a false "Box disconnected" Repair. Known limit: if Home Assistant is off at 09:00 the automation does **not** run late (the integration does not know about automations): a Holiday set for the night stays the stored goal and is restored on return, so go back to Daily from the selector. The selector keeps the last known mode while offline; use `dati_non_aggiornati` to know whether it is confirmed. Kitchen/Boost refused are never delivered; display changes are adopted only with a stable Box.
**Uninstall:** delete the integration entry, remove `custom_components/aldes_vmc`, restart.
**Credits:** Aldes Bridge by saniho (MIT). Not affiliated with Aldes.
