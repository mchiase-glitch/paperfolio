# Progetto: PaperFolio – Simulatore di portafoglio multi-strumento

## Obiettivo
App personale per esercitarmi a investire con denaro virtuale (paper trading).
L'interfaccia deve ricordare l'home banking Fideuram: per ogni posizione
quantità, prezzo medio di carico, prezzo attuale, controvalore e plus/minus.
La userò SOPRATTUTTO DAL TELEFONO: progetta prima per il mobile.
Non so programmare. Lavoriamo per fasi brevi; alla fine di ogni fase aggiorna
CONTEXT.md con stato, decisioni prese e prossimi passi.

## Stack
- Backend: Python + FastAPI, database SQLite
- Frontend: PWA (HTML/CSS/JS leggero), installabile sulla Home del telefono
- Dati: modulo `data_provider` con un adattatore per ciascuna fonte. Fonte
  principale: yfinance. I prezzi ritardati di circa 15 minuti vanno bene, ma
  va sempre mostrato l'orario dell'ultimo prezzo. Per gli strumenti che
  yfinance non copre (obbligazioni MOT, certificati, derivati IDEM) proponi
  una fonte alternativa; se non esiste una fonte affidabile e gratuita,
  prevedi l'inserimento manuale del prezzo con l'etichetta "prezzo manuale".
- Calendari di borsa: `exchange_calendars` o libreria equivalente

## Flusso di sviluppo e deploy
- Sviluppo sul mio PC di casa (Lenovo, Linux). Produzione sul Raspberry Pi
  (mercuberryPi) in Docker. Il passaggio tra i due avviene tramite GitHub,
  come per i miei altri progetti.
- Crea il progetto come repository git, da collegare a un repository GitHub
  PRIVATO. Dammi i comandi da eseguire per crearlo e collegarlo.
- `.gitignore`: escludi il database SQLite, i file `.env`, le cache e i log.
  Nel repository non devono finire dati o credenziali.
- Configurazione tramite `.env`, con un `.env.example` versionato
- Il database del Pi vive in un volume Docker o in una cartella dati esterna al
  repository, così un `git pull` non lo sovrascrive mai. Sul Lenovo uso un
  database di sviluppo separato.
- Script `deploy.sh` da lanciare sul Pi: `git pull`, rebuild e riavvio del
  container (`docker compose up -d --build`), backup del database prima di ogni
  aggiornamento
- Le migrazioni dello schema del database devono essere automatiche e
  versionate (es. Alembic), in modo che un aggiornamento non faccia perdere
  i dati del portafoglio
- Accesso remoto tramite Tailscale, già configurato sul Pi e in uso per CantinApp
  e altri progetti. Scegli una porta libera e dimmi quale hai usato.
- A fine fase: commit con un messaggio chiaro e istruzioni per il deploy sul Pi

## Strumenti
Ogni strumento ha: tipo, mercato, valuta, paese dell'emittente, categoria fiscale.
- Azioni: Borsa Italiana (ITA), altre borse europee (EUR), USA
- ETF: armonizzati UCITS
- Obbligazioni: titoli di Stato italiani ed esteri inclusi nella white list,
  obbligazioni societarie. Prezzo in % del nominale (corso secco) più il rateo
  di interessi, cedole e rimborso a scadenza.
- Derivati (opzioni USA, opzioni e futures IDEM, certificati, covered warrant):
  per ora NON vanno sviluppati. L'architettura deve però già prevederli:
  - modello dati con lato della posizione (long/short), moltiplicatore,
    sottostante, strike, scadenza, call/put
  - campi e servizi pronti per i margini e la liquidazione giornaliera di
    futures e opzioni vendute
  - un motore ordini che non dia per scontato il solo acquisto: il divieto di
    vendita allo scoperto deve essere una regola configurabile, non un vincolo
    scritto nel codice
  Nella prima implementazione futura i derivati saranno solo in acquisto.

## Conto e valute
- Conto in EUR con capitale iniziale che imposto io
- Strumenti in USD: conversione al cambio di mercato più uno spread
  modificabile (provvisorio 0,10%), sempre a mio sfavore sia in acquisto sia
  in vendita. Il riepilogo mostra sia il cambio di mercato sia quello applicato.
- Portafoglio valorizzato in EUR; per gli strumenti in valuta va mostrato anche
  il prezzo nella valuta originale

## Ordini
- Ordini a mercato, indicando la quantità (per le obbligazioni, il nominale)
- Borsa aperta: esecuzione immediata all'ultimo prezzo disponibile
- Borsa chiusa: l'ordine resta "in attesa" e viene eseguito al primo prezzo dopo
  l'apertura (tramite un job pianificato); l'ordine si può annullare
- Gli acquisti in attesa prenotano la liquidità con un margine modificabile
  (provvisorio +5%); all'esecuzione la parte non usata viene rilasciata
- Controlli: liquidità sufficiente; niente vendita allo scoperto (regola
  configurabile)
- Prima della conferma, riepilogo con: prezzo, rateo, cambio, controvalore,
  commissione, Tobin tax, imposta stimata, importo netto

## Commissioni (modificabili da Impostazioni, una tabella per tipo di strumento)
Valori iniziali uguali per tutti gli strumenti:
| Mercato | Fisso (€) | Percentuale | Minimo (€) |
|---|---|---|---|
| ITA | 3,00 | 0,07% | 5,00 |
| EUR | 12,00 | 0,07% | 5,00 |
| USA | 6,00 | 0,07% | 5,00 |
Commissione = max(fisso + percentuale × controvalore in EUR, minimo)
Tobin tax: 0,1% sugli acquisti di azioni italiane (non su ETF né obbligazioni),
parametro modificabile.

## Eventi societari
- Dividendi azionari e distribuzioni degli ETF: spettano sulle quantità
  possedute alla data di stacco (ex-date) e vengono accreditati alla data di
  pagamento
- Dividendi esteri: prima la ritenuta alla fonte del paese dell'emittente
  (tabella per paese modificabile; USA provvisorio 15%, come con il modulo
  W-8BEN), poi il 26% italiano applicato al netto
- Cedole: accreditate al netto dell'aliquota prevista; rimborso a scadenza
- Split e raggruppamenti: adeguamento di quantità e prezzo medio di carico
- Ogni evento viene registrato nel ledger e compare nello storico

## Fiscalità (simulazione del regime amministrato italiano)
Le regole stanno in una tabella per categoria fiscale, modificabile, così da
poter recepire eventuali riforme:
- Azioni, obbligazioni societarie, derivati: plus e minus sono redditi diversi,
  tassati al 26% e compensabili con lo zainetto
- Titoli di Stato della white list: aliquota effettiva 12,5%, ottenuta
  applicando il 26% a una base imponibile pari al 48,08%; anche le minus
  entrano nello zainetto al 48,08%
- ETF armonizzati: le plus sono redditi di capitale (26%, NON compensabili),
  le minus sono redditi diversi (entrano nello zainetto)
- Dividendi e cedole: redditi di capitale, mai compensabili
- Rateo di interessi: tassato con l'aliquota dello strumento al momento
  dell'incasso
- Zainetto: ogni minus vale fino al 31/12 del quarto anno successivo; si usano
  prima le minus più vecchie
- Imposta di bollo: 0,20% annuo sul controvalore di mercato degli strumenti,
  pro rata per i giorni di detenzione, addebitata in liquidità al 31/12 o alla
  chiusura/reset del portafoglio. Va mostrata la stima maturata nell'anno in corso.
- P&L mostrato sia lordo sia netto (al netto di commissioni, imposte e bollo)

## Schermate
1. **Portafoglio** (home): valore totale, liquidità disponibile e prenotata,
   P&L del giorno e totale (realizzato e non realizzato, lordo e netto),
   posizioni in card raggruppate per tipo di strumento
2. **Dettaglio strumento**: quotazione, mini-grafico, la mia posizione,
   Compra/Vendi; per le obbligazioni anche cedola, scadenza e rendimento a scadenza
3. **Cerca**: per nome, ticker o ISIN, con filtro per tipo di strumento
4. **Ordini e movimenti**: ordini in attesa ed eseguiti, dividendi, cedole,
   bollo, eventi; esportazione in CSV
5. **Fiscale**: imposte pagate per categoria, zainetto con le scadenze, bollo,
   riepilogo annuale
6. **Impostazioni**: capitale, commissioni, aliquote, ritenute, spread di cambio,
   margine di prenotazione, bollo, reset del portafoglio

## Piano delle fasi
1. Azioni (ITA/EUR/USA), cambio con spread, commissioni, ordini in attesa,
   fiscalità al 26% con zainetto, bollo, repository GitHub e deploy sul Pi
2. ETF, dividendi, split
3. Obbligazioni (rateo, cedole, rimborso, regime 12,5%)
4. Extra: grafico storico del portafoglio confrontato con un indice, watchlist,
   ordini limite/stop, più portafogli
5. (Futura) Derivati in solo acquisto, sulla base della predisposizione

## Vincoli tecnici
- Importi sempre in Decimal, mai in float
- Ledger append-only (solo aggiunte, nessuna modifica): saldi e posizioni si
  ricalcolano sempre partendo da lì
- Test automatici per ogni regola di calcolo: commissioni, prezzo medio, cambio
  con spread, ciascuna categoria fiscale, zainetto con scadenze, ratei, dividendi
  esteri, split, bollo pro rata, ordini in attesa
- Orari salvati in UTC e mostrati in ora di Roma

## Primo passo
Non scrivere ancora codice. Proponi l'architettura e lo schema del database e
verifica quali fonti dati coprono ciascun tipo di strumento. Poi crea CONTEXT.md
e aspetta la mia approvazione.
