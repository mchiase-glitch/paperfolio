# PaperFolio – Contesto di progetto

## Stato attuale
**Fase 1 completata** (19/11/2026): azioni ITA/EUR/USA, cambio con spread, commissioni, ordini in attesa,
fiscalità 26% con zainetto, bollo, PWA mobile, Docker e deploy sul Pi. 39 test automatici superati.
**Non ancora fatto**: repository GitHub e primo deploy sul Pi (servono i comandi qui sotto, da lanciare a mano).

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
  scheduler.py       ordini in attesa (ogni 60 s), valutazione giornaliera (23:00), bollo (1° gennaio)
  api/               portfolio, instruments, orders (+ movimenti e CSV), fiscal, settings
  services/          commission, fx, prices, positions, tax, orders, portfolio, market_hours, settings
  data_provider/     base (interfaccia), yfinance_adapter, mapping (borse/paesi)
backend/alembic/versions/0001_schema_iniziale.py
backend/tests/       39 test
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
- **Derivati e obbligazioni**: campi già presenti nello schema (moltiplicatore, sottostante, strike, scadenza, call/put, lato posizione, margine; cedola, frequenza, scadenza), nessuna logica ancora.

## Fonti dati
| Tipo | Fonte |
|---|---|
| Azioni Borsa Italiana, UE, USA | yfinance ✅ (verificato: ENI.MI, STLAM.MI, SAP.DE, AAPL, ricerca anche per ISIN) |
| ETF UCITS | yfinance (fase 2) |
| Cambi | yfinance (`EURUSD=X`) |
| BTP/CCT, obbligazioni MOT, certificati, derivati IDEM | nessuna fonte gratuita affidabile → prezzo manuale |

## Punti aperti / da verificare
1. **Porta 8042 sul Pi**: non conosco le porte di CantinApp e degli altri progetti; verificare con `sudo ss -tlnp | grep 8042` (nessun output = libera). Se occupata, cambiare `PORT` in `.env`.
2. **Compensazione nello stesso anno**: nel regime amministrato reale una minus realizzata dopo una plus nello stesso anno può dare il rimborso dell'imposta già pagata. Ora la minus va solo nello zainetto per le plus future. Da decidere se simularlo.
3. **Installazione PWA su Android**: Chrome richiede HTTPS. Su Tailscale si può usare `tailscale serve` (vedi sotto). Su iPhone "Aggiungi a Home" funziona anche in HTTP.
4. **Variazione del giorno**: calcolata solo sulle posizioni ancora aperte (le posizioni chiuse oggi non entrano nel risultato del giorno).
5. Sviluppo: il PROMPT parla del Lenovo Linux; finora il lavoro è stato fatto su un PC Windows. I comandi sotto valgono per entrambi.

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
git remote add origin git@github.com:<TUO-UTENTE>/paperfolio.git
git push -u origin main
```

## Deploy sul Raspberry Pi
Primo avvio:
```bash
cd ~ && git clone git@github.com:<TUO-UTENTE>/paperfolio.git && cd paperfolio
sudo ss -tlnp | grep 8042          # deve non stampare nulla
cp .env.example .env && nano .env  # PORT, PAPERFOLIO_DATA_DIR, INITIAL_CAPITAL
chmod +x deploy.sh && ./deploy.sh
```
Aggiornamenti successivi: `cd ~/paperfolio && ./deploy.sh` (backup DB → git pull → rebuild → verifica).
- Dati e backup: `~/paperfolio-data/` (fuori dal repository; ultimi 30 backup in `backups/`).
- App: `http://<nome-pi-tailscale>:8042`
- HTTPS facoltativo per installare la PWA su Android: `sudo tailscale serve --bg --https=8443 http://127.0.0.1:8042` → `https://<nome-pi>.<tailnet>.ts.net:8443`
- Log: `docker compose logs --tail 100 -f`

---

## Prossimi passi – Fase 2 (ETF, dividendi, split)
1. Abilitare gli ETF UCITS (categoria `etf_armonizzati`: plus redditi di capitale, minus nello zainetto — regole già testate).
2. Dividendi e distribuzioni: rilevazione da yfinance (`Ticker.dividends`), diritto sulle quantità all'ex-date, accredito alla data di pagamento; per gli esteri ritenuta del paese (`withholding_rates`) poi 26% sul netto.
3. Split e raggruppamenti: riga `split` nel ledger, adeguamento di quantità e prezzo medio.
4. Decidere sul punto aperto 2 (rimborso imposta nello stesso anno).

## Piano delle fasi
1. ✅ Azioni, cambio con spread, commissioni, ordini in attesa, fiscalità 26% + zainetto, bollo, Docker/deploy
2. ETF, dividendi, split
3. Obbligazioni (rateo, cedole, rimborso, regime 12,5%)
4. Extra: grafico storico vs indice, watchlist, ordini limite/stop, più portafogli
5. (Futura) Derivati in solo acquisto
