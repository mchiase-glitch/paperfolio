# PaperFolio – Contesto di progetto

## Stato attuale
**Fase 4 completata** (20/11/2026): più portafogli, ordini limite e stop con scadenza, titoli seguiti (watchlist),
grafico del rendimento confrontato con un indice. 86 test automatici superati.
**Fase 3 completata** (20/11/2026): obbligazioni a tasso fisso e zero coupon (titoli di Stato white list al 12,5%,
societarie al 26%), rateo con regolamento T+2, cedole, rimborso a scadenza, rendimento a scadenza. 68 test automatici superati.
**Fase 2 completata** (19/11/2026): ETF armonizzati, dividendi e distribuzioni (ritenuta estera + 26%),
frazionamenti e raggruppamenti. 51 test automatici superati.
**Fase 1 completata** (19/11/2026): azioni ITA/EUR/USA, cambio con spread, commissioni, ordini in attesa,
fiscalità 26% con zainetto, bollo, PWA mobile, Docker e deploy sul Pi.
**Repository e Pi**: repository privato `mchiase-glitch/paperfolio` su GitHub; app attiva sul Pi (mercuberryPi) sulla porta 8042, con HTTPS tramite `tailscale serve` sulla 8443.
**In produzione** (21/11/2026): la Fase 4 è installata sul Pi e verificata dal telefono (PWA installata). Prossimo passo: periodo d'uso reale per raccogliere correzioni; la Fase 5 solo su richiesta.

---

## Stack
- Backend: Python 3.13 (Docker) / 3.14 (PC), FastAPI, SQLAlchemy, SQLite, Alembic, APScheduler
- Dati: yfinance (prezzi ritardati ~15 min, sempre con orario), `exchange_calendars` per gli orari di borsa
- Frontend: PWA in HTML/CSS/JS senza framework, servita dal backend sulla stessa porta
- **Porta: 8042** (da verificare sul Pi, vedi sotto)

## Struttura
```
backend/app/
  main.py            avvio: migrazioni automatiche, valori iniziali, job pianificati
  config.py          lettura .env
  database.py        Decimal salvati come testo, orari sempre UTC
  models.py          tabelle
  migrate.py         alembic upgrade head all'avvio
  scheduler.py       ordini in attesa (ogni 60 s), eventi societari (7:00), valutazione giornaliera (23:00), bollo (1° gennaio)
  api/               portfolio (+ storico e portafogli), instruments, orders (+ movimenti e CSV), events, fiscal, settings, watchlist
  services/          commission, fx, prices, positions, tax, orders, portfolio, corporate_events, bonds, market_hours, settings
  data_provider/     base (interfaccia), yfinance_adapter, mapping (borse/paesi)
backend/alembic/versions/  0001_schema_iniziale, 0002_eventi_societari, 0003_obbligazioni, 0004_extra
backend/tests/       86 test
frontend/            index.html, css, js/screens/*, manifest.json, sw.js, icons/
Dockerfile, docker-compose.yml, deploy.sh, .env.example
```

## Decisioni prese
- **Importi**: sempre `Decimal`, salvati come testo; all'API arrivano come stringhe esatte. Arrotondamento al centesimo solo sugli addebiti.
- **Ledger append-only** (`ledger_entries`, `loss_usages`): trigger SQL rifiutano UPDATE e DELETE. Posizioni, liquidità e zainetto si ricalcolano sempre dal ledger.
  Rispetto alla proposta iniziale lo zainetto non ha un campo "usato" modificabile: ogni utilizzo è una riga in `loss_usages`.
- **Tabelle non-ledger modificabili**: `orders` (stato dell'ordine), `prices`/`fx_rates` (cache), `daily_valuations`, impostazioni.
- **Prezzo medio di carico**: media ponderata; la vendita non lo cambia. Mostrato nella valuta dello strumento. Il costo fiscale in EUR include le commissioni di acquisto (non la Tobin tax).
- **Cambio**: acquisto a cambio di mercato × (1 − spread), vendita × (1 + spread): sempre a sfavore. Portafoglio valorizzato al cambio di mercato.
- **Ordini a mercato**: eseguiti subito solo se la borsa è aperta *e* l'ultimo prezzo è successivo all'apertura della seduta; altrimenti restano in attesa e il job li esegue al primo prezzo dopo l'apertura. In esecuzione la liquidità viene ricontrollata: se il prezzo è salito oltre la disponibilità l'ordine viene **rifiutato** (con nota).
- **Prenotazione**: (controvalore + commissione + Tobin) × (1 + margine 5%).
- **Quantità**: intere per azioni ed ETF.
- **Vendita allo scoperto**: regola `allow_short_selling` nelle impostazioni (default no). Le posizioni short vere arriveranno con i derivati.
- **Fiscalità**: regole per categoria in `tax_rules` (aliquota, base imponibile, plus "diversi"/"capitale", minus nello zainetto sì/no). Imposta addebitata nella stessa riga della vendita. Zainetto usato dalle minus più vecchie, valide fino al 31/12 del quarto anno successivo.
- **Bollo**: valutazione di fine giornata salvata in `daily_valuations` (anche dopo ogni ordine eseguito); i giorni mancanti riprendono l'ultimo valore. Addebito al 31/12 (alle 23:59 ora di Roma, anche in recupero all'avvio se il Pi era spento) o al reset.
- **Reset**: chiude il conto (bollo maturato addebitato, ordini in attesa annullati) e ne apre uno nuovo. Lo storico resta nel database.
- **Paese emittente** da yfinance: decide Tobin tax (es. Stellantis = NL, niente Tobin) e in futuro le ritenute.
- **Prezzo manuale**: strumenti con `data_source = manual`, prezzo inserito dall'app, sempre etichettato "prezzo manuale".
- **ETF (fase 2)**: negoziabili solo se quotati su borse europee; gli ETF USA sono bloccati perché non UCITS. yfinance non dice se un ETF è armonizzato: si assume che lo siano tutti quelli quotati in Europa. Paese = prefisso dell'ISIN (IE, LU...) quando la fonte non lo fornisce. Niente Tobin tax.
- **Eventi societari (fase 2)**: tabella `corporate_events` (fatti dello strumento, modificabili finché non registrati); gli effetti sul conto vanno nel ledger con `corporate_event_id`. Job ogni mattina alle 7:00 e all'avvio: legge da yfinance dividendi e split dalla data del primo acquisto, poi applica ciò che è maturato.
- **Dividendi**: spettano alle quantità possedute prima della mezzanotte (ora di Roma) del giorno di stacco: chi compra il giorno dello stacco non ha diritto, chi vende quel giorno sì. Accredito alla data di pagamento. Calcolo: lordo in valuta → EUR al cambio di vendita con spread → ritenuta del paese emittente (solo azioni estere, tabella `withholding_rates`) → aliquota italiana della categoria sul netto. Gli ETF non subiscono ritenute estere.
- **Data di pagamento**: yfinance la dà solo per il prossimo dividendo dei titoli USA. Negli altri casi si stima (Italia/UE: stacco + 2 giorni lavorativi; ETF: + 14 giorni; USA: + 21 giorni), con l'etichetta "stimato" e la possibilità di correggerla dal dettaglio del titolo.
- **Importi dei dividendi**: yfinance riporta i dividendi passati divisi per gli split successivi; il programma li riporta al valore reale.
- **Split**: quantità × rapporto e costo invariato, quindi il prezzo medio di carico si adegua. Nei raggruppamenti la frazione viene liquidata senza commissioni al prezzo corrente, con calcolo fiscale.
- **Risultato realizzato**: comprende dividendi e distribuzioni (lordo e netto).
- **Eventi manuali**: dal dettaglio del titolo si aggiungono dividendi e split che la fonte non riporta.
- **Obbligazioni (fase 3)**:
  - Inserimento manuale dalla schermata Cerca (ISIN, cedola, frequenza, scadenza, emissione facoltativa, taglio minimo, convenzione giorni, prezzo). Simbolo = ISIN, borsa MOT (calendario XMIL), `data_source = manual`.
  - Quantità = valore nominale, multiplo del taglio minimo (default 1.000). Prezzo in % del nominale, corso secco: il moltiplicatore dello strumento è 0,01, così controvalore = nominale × prezzo / 100 con la stessa formula delle azioni.
  - **Regolamento T+2** giorni di borsa (calendario XMIL). Il rateo si calcola alla data di regolamento e la stessa data decide il diritto alla cedola: la cedola spetta a chi ha operazioni regolate *prima* della data di pagamento.
  - **Rateo**: ACT/ACT ICMA (giorni effettivi / giorni del periodo cedolare) oppure 30E/360. Cedole regolari ricavate a ritroso dalla scadenza; la prima cedola è ridotta se l'emissione cade dentro il periodo (cedola corta).
  - **Tassazione del rateo** come nei fissati bollati italiani: chi vende incassa il rateo e paga l'imposta dello strumento (12,5% o 26%); chi compra paga il rateo lordo e riceve il credito d'imposta corrispondente; la cedola è tassata per intero. Risultato: si paga l'imposta solo sull'interesse maturato nel periodo di possesso. Nel ledger: `accrued_interest_eur`, `interest_tax_eur` (negativo = credito), `settlement_date`.
  - Plus/minus sul corso secco, con le regole della categoria (white list: base 48,08% anche per le minus nello zainetto). Niente Tobin tax.
  - **Cedole e rimborso**: alla creazione del titolo si genera il calendario (`corporate_events` di tipo `coupon` e `redemption`, fonte `schedule`); il job delle 7:00 accredita le cedole al netto e alla scadenza rimborsa al 100% senza commissioni, calcolando plus/minus. Dopo la scadenza (o se il regolamento cadrebbe dopo) il titolo non è più negoziabile e gli ordini in attesa vengono rifiutati.
  - **Rendimento a scadenza** (nel dettaglio): tasso annuo composto che uguaglia prezzo + rateo ai flussi futuri (giorni/365). Netto: cedole e rateo al netto dell'imposta, imposta sullo scarto positivo tra 100 e prezzo; esclusi commissioni e bollo.
  - **Portafoglio**: controvalore al corso secco; il rateo maturato è mostrato a parte, entra nel valore totale e nel non realizzato. Il realizzato comprende cedole e ratei incassati meno ratei pagati.
- **Più portafogli (fase 4)**: più conti aperti insieme, ciascuno con liquidità, posizioni, ordini, zainetto e bollo separati. Il portafoglio attivo è salvato sul server (`app_settings.current_account_id`), quindi è lo stesso su telefono e PC; si cambia dal pulsante col nome in alto a destra. Creazione, rinomina e chiusura da Impostazioni; non si può chiudere l'ultimo (c'è il reset). Commissioni, aliquote e parametri sono comuni a tutti. Il reset mantiene il nome.
- **Ordini limite e stop (fase 4)**: `orders.order_type` (market/limit/stop), `trigger_price`, `expires_on` (default +30 giorni). Limite: compra a prezzo ≤ limite, vende a prezzo ≥ limite. Stop: compra quando il prezzo sale alla soglia, vende quando scende alla soglia (stop loss). Il job ogni minuto, a borsa aperta e con un prezzo della seduta, esegue al prezzo di mercato del momento (non al limite). Se la condizione è già vera all'inserimento l'ordine si esegue subito. Prenotazione in acquisto al prezzo peggiore prevedibile (il limite, o il maggiore tra soglia di stop e prezzo attuale) + margine. Scaduta la validità l'ordine passa a "Scaduto" e libera la liquidità.
- **Watchlist (fase 4)**: tabella `watchlist`, comune a tutti i portafogli; stella nel dettaglio del titolo, elenco "Titoli seguiti" in fondo al Portafoglio.
- **Grafico del rendimento (fase 4)**: valore totale di ogni sera = controvalore salvato in `daily_valuations` + liquidità ricostruita dal ledger; ultimo punto = valore attuale; primo punto = apertura del conto (capitale iniziale). Rendimento rispetto al capitale iniziale. Indici di confronto da yfinance (FTSE MIB, Euro Stoxx 50, MSCI World tramite ETF SWDA in €, S&P 500 in $), solo prezzo e senza dividendi, in base alla chiusura disponibile in ogni data; cache di un'ora.
- **Cache dell'interfaccia**: il server risponde con `Cache-Control: no-cache` ai file dell'interfaccia e il service worker li ricontrolla sempre, così dopo un deploy il telefono non mescola file vecchi e nuovi.
- **Derivati**: campi già presenti nello schema (moltiplicatore, sottostante, strike, scadenza, call/put, lato posizione, margine), nessuna logica ancora.

## Fonti dati
| Tipo | Fonte |
|---|---|
| Azioni Borsa Italiana, UE, USA | yfinance ✅ (verificato: ENI.MI, STLAM.MI, SAP.DE, AAPL, ricerca anche per ISIN) |
| ETF UCITS | yfinance ✅ (verificato: VHYL.MI, IUSA.DE; mancano paese e calendario) |
| Dividendi e split | yfinance ✅ (storico per data di stacco; data di pagamento solo per i titoli USA) |
| Cambi | yfinance (`EURUSD=X`) |
| BTP/CCT, obbligazioni MOT, certificati, derivati IDEM | nessuna fonte gratuita affidabile → prezzo manuale (obbligazioni: % del nominale, corso secco) |

## Punti aperti / da verificare
1. **Porta 8042 sul Pi**: non conosco le porte di CantinApp e degli altri progetti; verificare con `sudo ss -tlnp | grep 8042` (nessun output = libera). Se occupata, cambiare `PORT` in `.env`.
2. **Compensazione nello stesso anno**: nel regime amministrato reale una minus realizzata dopo una plus nello stesso anno può dare il rimborso dell'imposta già pagata. Ora la minus va solo nello zainetto per le plus future. Da decidere se simularlo.
3. **Installazione PWA su Android**: Chrome richiede HTTPS. Su Tailscale si può usare `tailscale serve` (vedi sotto). Su iPhone "Aggiungi a Home" funziona anche in HTTP.
4. **Variazione del giorno**: calcolata solo sulle posizioni ancora aperte (le posizioni chiuse oggi non entrano nel risultato del giorno).
5. Sviluppo: il PROMPT parla del Lenovo Linux; finora il lavoro è stato fatto su un PC Windows. I comandi sotto valgono per entrambi.
6. **ETC/ETN** (es. oro fisico): Yahoo potrebbe classificarli come ETF, ma fiscalmente sono redditi diversi, non redditi di capitale. Non vengono distinti.
7. **ETF con titoli di Stato**: nella realtà la quota di proventi riferibile ai titoli white list è tassata al 12,5%; qui tutto al 26%.
8. **Cambio dei dividendi in valuta**: si usa il cambio del momento in cui il job registra l'accredito, non quello esatto della data di pagamento (coincidono se il server è acceso quel giorno).
9. **Split e ordini in attesa**: un ordine inserito prima di uno split ed eseguito dopo mantiene la quantità originale.
10. **Obbligazioni non gestite**: tasso variabile (CCT), indicizzate all'inflazione (BTP Italia, BTP€i), prime cedole lunghe, rimborsi anticipati o a rate (amortizing), premi fedeltà.
11. **Scarto di emissione** (BOT, zero coupon, titoli emessi sotto la pari): nella realtà è reddito di capitale tassato a parte; qui tutta la differenza tra prezzo e rimborso è trattata come plus/minus.
12. **Cedole nei giorni festivi**: accreditate nella data teorica, non nel primo giorno lavorativo successivo (il rateo non cambia).
13. **Prezzo manuale e ordini**: con prezzo manuale l'ordine si esegue subito se il MOT è aperto, al prezzo inserito, anche se vecchio. Conviene aggiornarlo prima di comprare o vendere. Vale anche per limite e stop: scattano quando aggiorni il prezzo.
14. **Ordini limite e stop con prezzi ritardati**: il controllo usa l'ultimo prezzo di yfinance (ritardato ~15 min, letto ogni minuto). Un movimento rapido che tocca il limite e torna indietro tra due letture non viene visto; l'esecuzione avviene al prezzo letto, che per uno stop può essere peggiore della soglia (come nella realtà in caso di gap).
15. **Grafico**: mancano i giorni in cui il server era spento; il valore storico non comprende i ratei. Il rendimento non tiene conto di versamenti successivi (oggi non previsti).

---

## Sviluppo in locale
Linux (Lenovo):
```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q                                   # test
uvicorn app.main:app --port 8042 --reload   # app su http://localhost:8042
```
Windows: stessi comandi con `.venv\Scripts\python.exe -m pip ...`, `-m pytest`, `-m uvicorn ...`.
Il database di sviluppo è `backend/data/paperfolio.db` (escluso da git), separato da quello del Pi.

## Repository GitHub (privato)
Opzione A, con GitHub CLI (`gh auth login` la prima volta):
```bash
gh repo create paperfolio --private --source . --remote origin --push
```
Opzione B, dal sito: crea il repository **privato** `paperfolio` vuoto su github.com, poi:
```bash
git remote add origin git@github.com:mchiase-glitch/paperfolio.git
git push -u origin main
```

## Deploy sul Raspberry Pi
Primo avvio:
```bash
cd ~ && git clone git@github.com:mchiase-glitch/paperfolio.git && cd paperfolio
sudo ss -tlnp | grep 8042          # deve non stampare nulla
cp .env.example .env && nano .env  # PORT, PAPERFOLIO_DATA_DIR, INITIAL_CAPITAL
chmod +x deploy.sh && ./deploy.sh
```
Aggiornamenti successivi: `cd ~/paperfolio && ./deploy.sh` (backup DB → git pull → rebuild → verifica).
- Dati e backup: `~/paperfolio-data/` (fuori dal repository; ultimi 30 backup in `backups/`).
- App: `http://<nome-pi-tailscale>:8042`
- HTTPS facoltativo per installare la PWA su Android: `sudo tailscale serve --bg --https=8443 http://127.0.0.1:8042` → `https://<nome-pi>.<tailnet>.ts.net:8443`
- Log: `docker compose logs --tail 100 -f`
- Il serve di Tailscale va abilitato una volta sola per il tailnet (link login.tailscale.com mostrato dal comando).

### Aggiornare l'app sul telefono
Non serve reinstallare: dopo `git push` (PC) e `./deploy.sh` (Pi) basta chiudere del tutto l'app e riaprirla.
I dati stanno nel database sul Pi, non sul telefono. Se dovesse restare una schermata vuota o vecchia:
Android Chrome → lucchetto → Impostazioni sito → Cancella e reimposta; iPhone → Impostazioni → Safari → Avanzate → Dati dei siti web.

---

## Prossimi passi – Fase 5 (futura: derivati in solo acquisto)
1. Opzioni USA e IDEM, futures IDEM, certificati, covered warrant: anagrafica con sottostante, strike, scadenza, call/put e moltiplicatore (campi già nello schema).
2. Fonte prezzi: yfinance copre le opzioni USA (catena per scadenza); per IDEM, certificati e covered warrant serve il prezzo manuale.
3. Solo acquisto (long): il divieto di vendita allo scoperto resta attivo. Margini e liquidazione giornaliera dei futures da progettare (campi `margin_eur`, `position_side` già presenti).
4. Fiscalità: redditi diversi al 26% con zainetto (categoria `derivati` già presente); scadenza delle opzioni senza valore come minusvalenza.
5. Restano da decidere i punti aperti 2 (rimborso dell'imposta nello stesso anno) e 7 (ETF con titoli di Stato).

## Piano delle fasi
1. ✅ Azioni, cambio con spread, commissioni, ordini in attesa, fiscalità 26% + zainetto, bollo, Docker/deploy
2. ✅ ETF, dividendi, split
3. ✅ Obbligazioni (rateo, cedole, rimborso, regime 12,5%)
4. ✅ Extra: grafico storico vs indice, watchlist, ordini limite/stop, più portafogli
5. (Futura) Derivati in solo acquisto
