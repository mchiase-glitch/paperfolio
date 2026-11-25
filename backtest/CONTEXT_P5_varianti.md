# CONTEXT — P5 (RSI a 2 giorni): test delle varianti

*Progetto PaperFolio. Creato il 25/11/2026. Da leggere all'inizio di ogni sessione di lavoro su P5.*

## 1. Obiettivo

Capire se P5 ha un vantaggio reale una volta corretti i punti in cui si allontana dal sistema originale di Connors, **senza cadere nell'overfitting**. Questo è un lavoro di **solo backtest**: il portafoglio P5 dal vivo non si tocca finché la fase 5 non è chiusa.

## 2. Punto di partenza (V0, backtest al 25/11/2026)

- Periodo 4/1/2010–25/11/2026, 100.000 € iniziali, valore finale 50.459 €.
- Rendimento annuo netto −4,0% (prova 2010–2018: −0,4%; verifica 2019–2026: −7,9%). Perdita massima −60%.
- 3.584 acquisti; rendimento lordo medio per operazione +0,15% (mediana +0,54%).
- Costo per giro: circa 0,23% (circa 0,4% sui titoli USA, compreso il cambio).
- Uscite sotto la media a 200: 514 vendite, −641 € medi l'una, 8% in utile.
- Freno sul drawdown acceso per 1.421 giorni su circa 4.300.

## 3. Ipotesi da verificare (scelte PRIMA di vedere i risultati)

1. **H1 — Esecuzione.** Il guadagno delle strategie di ritorno alla media arriva soprattutto nelle ore di chiusura (overnight). Eseguendo all'apertura del giorno dopo se ne perde una parte.
2. **H2 — Uscita sotto la media a 200.** È una regola aggiunta rispetto a Connors (lui non usa stop) e taglia le posizioni nel punto peggiore.
3. **H3 — Freno sul drawdown.** Per una strategia di ritorno alla media è controproducente: blocca gli acquisti proprio dopo i cali.
4. **H4 — Soglia più severa.** Con RSI < 5 ci sono meno operazioni (quindi meno costi) e rimbalzi medi più ampi.

## 4. Regole anti-overfitting (vincolanti)

- **Le varianti sono solo quelle elencate al §5.** Non se ne aggiungono altre dopo aver visto i risultati. Una nuova idea va scritta al §9 e testata in un ciclo successivo, su dati nuovi.
- **Niente ottimizzazione dei parametri.** RSI 10, media a 5, media a 200 e stop a 10 giorni restano fissi, salvo V4 e il test di robustezza al §6.
- Tutti i risultati si riportano sempre **separati tra prova (2010–2018) e verifica (2019–2026)**, mai soltanto sull'intero periodo.
- I criteri per accettare una variante (§7) sono fissati adesso e non si cambiano dopo.
- Si registrano **tutte** le prove fatte, anche quelle andate male, nel registro al §10.

## 5. Varianti da testare

Ogni variante cambia **una sola cosa** rispetto a V0, tranne V5.

| Codice | Modifica rispetto a V0 | Ipotesi |
|---|---|---|
| V0 | nessuna (punto di riferimento, da rilanciare con il codice attuale) | — |
| V1 | esecuzione al **prezzo di chiusura del giorno del segnale**, sia in entrata sia in uscita | H1 |
| V2 | **eliminata l'uscita sotto la media a 200**; restano l'uscita sopra la media a 5 e lo stop a 10 giorni | H2 |
| V3 | **freno sul drawdown disattivato solo per P5** | H3 |
| V4 | entrata con **RSI a 2 giorni < 5** invece di < 10 | H4 |
| V5 | V1 + V2 + V3 insieme (combinazione decisa in anticipo) | H1–H3 |

### Note di implementazione

- **V1:** il segnale calcolato sulla chiusura ed eseguito alla stessa chiusura approssima un ordine MOC (al prezzo di chiusura) inviato 10–15 minuti prima della fine della seduta. Per compensare questa approssimazione si aggiunge uno **slippage dello 0,05% per lato** solo in V1 e V5. Va indicato nel report.
- **V3:** il freno deve diventare un **parametro della singola strategia** (per esempio `drawdown_brake: true/false`), non un cambio globale. Le altre strategie devono restare identiche: verifica che i loro backtest diano gli stessi numeri di prima della modifica.
- Tutte le varianti si attivano da configurazione o da opzioni del backtest, senza copiare il codice della strategia. Il codice della strategia dal vivo resta unico.
- Prima di partire individua nel codice dove sono definite regole di P5, esecuzione e freno, e annotalo qui sotto:
  - regole P5: `backend/app/services/strategies/p5_rsi2.py` → `P5Rsi2.generate_decisions` (entrata, uscite, posti). Indicatori in `services/indicators.py` (`rsi_series`, `prefix_sums`).
  - esecuzione (apertura del giorno dopo): `backend/app/services/backtest.py` → `BacktestEngine._signal` (ordini creati alla chiusura) e `_execute_pending` (eseguiti all'apertura del giorno di borsa dopo, prima le vendite). Dal vivo: `services/auto_portfolio.py` → `run_strategy` (ordini al momento del controllo, alle 17:00 per le strategie su più liste).
  - freno sul drawdown: soglie e regola in `backend/app/services/auto_rules.py` (`brake_state`: si accende a −20%, si spegne a −10%, massimo degli ultimi 365 giorni). Nel backtest in `BacktestEngine.run`; dal vivo in `auto_portfolio._update_drawdown_brake`. Ogni strategia lo applica nel proprio `generate_decisions` (niente nuovi acquisti).
- **Come si attivano le varianti** (fase 1, 25/11/2026). Parametri di P5 (valgono anche dal vivo, con default invariati):
  - `drawdown_brake: false` → V3. È un parametro di tutte le strategie (`BaseStrategy.uses_drawdown_brake`), predefinito `true`; con `false` la strategia riceve sempre "freno spento" e i giorni di freno contati nel report sono 0.
  - `exit_below_sma_long: false` → V2.
  - `rsi_entry: 5` → V4 (e 15 per il test di robustezza).

  Opzioni del solo backtest, in `params["backtest_options"]` (`backtest.EngineOptions`):
  - `execution: "close"` + `slippage: 0.0005` → V1. Se un titolo quel giorno non ha quotato, l'ordine passa all'apertura successiva come in V0.
  - `costs: "low"` → C-basso (`backtest.LOW_COSTS`: 0,025% per lato, minimo 1 €, spread di cambio zero su operazioni e dividendi). La conversione iniziale unica verso il dollaro non è addebitata: su 100.000 € vale poche decine di euro.

## 6. Scenari di costo e robustezza

- **Scenari di costo.** Non sono varianti della strategia: ogni variante si lancia due volte.
  - **C-attuale:** commissioni attuali (come V0).
  - **C-basso:** broker a basso costo, circa 0,025% per lato senza parte fissa, minimo 1 €. Conto multivaluta: nessuno spread di cambio sulle singole operazioni USA; si converte una volta sola all'inizio. Tobin tax invariata.
- **Robustezza.** Solo per la variante migliore secondo il §7: rilancio con soglia RSI 5 / 10 / 15. Il risultato deve restare positivo e simile su tutte e tre; se funziona con una sola soglia, è da scartare.

## 7. Criteri di accettazione (fissati il 25/11/2026)

Una variante è promossa solo se, nello scenario **C-attuale oppure in C-basso** (va dichiarato quale), rispetta tutte queste condizioni:

1. rendimento annuo netto > 0 **sia in prova sia in verifica**;
2. migliore di V0 sia in prova sia in verifica;
3. rendimento lordo medio per operazione > costo medio per giro;
4. perdita massima migliore di V0;
5. regge il test di robustezza del §6.

Se nessuna variante supera i criteri con C-attuale, la conclusione è: **P5 non è praticabile con il broker attuale.** Non si cercano altre varianti per "salvarla".

## 8. Output richiesto

Per ogni combinazione variante × scenario di costo, un report in `backtest/reports/p5_varianti/` (CSV + un riepilogo `.md`) con:

- rendimento annuo netto (totale, prova, verifica), volatilità, perdita massima, indice di Sharpe;
- numero di acquisti, rotazione annua;
- commissioni, Tobin, imposte, bollo;
- rendimento lordo medio e mediano per operazione, costo medio per giro;
- tabella per motivo di uscita (vendite, risultato lordo medio, % in utile);
- tabella per mercato (USA / Italia / Europa: acquisti, lordo, costi);
- giorni con il freno acceso;
- una tabella finale di confronto con tutte le varianti affiancate.

## 9. Fasi

- [x] **Fase 1:** individuare il codice (§5), rendere il freno un parametro della singola strategia, aggiungere le opzioni di esecuzione e di soglia RSI. Verificare che V0 riproduca i numeri del §2 e che le altre strategie non cambino.
  - *Chiusa il 25/11/2026.* V0 rilanciato con il codice nuovo: 50.459,29 €, identico al §2. P1 (FTSE MIB, S&P 100), P2 (FTSE MIB, Euro Stoxx 50, S&P 100), P3, P4 e P7 danno esattamente gli stessi numeri di prima: valore finale, operazioni, costi, imposte e giorni di freno. Il confronto è stato fatto sugli stessi dati in cache, senza scaricare nulla.
- [ ] **Fase 2:** lanciare V0–V5 negli scenari C-attuale e C-basso (12 backtest) e generare i report del §8.
- [ ] **Fase 3:** applicare i criteri del §7 e fare il test di robustezza sulla variante migliore.
- [ ] **Fase 4 (facoltativa):** verifica su un universo nuovo, mai usato prima (per esempio azioni STOXX 600 fuori da FTSE MIB ed Euro Stoxx 50), solo per la variante promossa.
- [ ] **Fase 5:** decisione. Se c'è una variante promossa, va in paper trading dal vivo come **P5b**, accanto a P5, per almeno 6 mesi prima di qualsiasi altra modifica. Per V1 dal vivo serve anche spostare il controllo vicino alla chiusura: circa 17:20 per Milano ed Europa, circa 21:45 per gli USA.

**Idee per cicli futuri** (non testarle adesso): RSI cumulativo (somma dell'RSI a 2 giorni su 2 giorni < 35, uscita con RSI a 2 giorni > 65); filtro di regime sull'indice invece del freno sul drawdown; posizioni dimensionate in base alla volatilità; 3 posizioni invece di 5.

## 10. Registro delle prove

| Data | Variante | Costi | Netto prova | Netto verifica | Perdita massima | Note |
|---|---|---|---|---|---|---|
| 25/11/2026 | V0 | C-attuale | −0,4% | −7,9% | −60% | punto di riferimento |
| 25/11/2026 | V0 | C-attuale | −0,4% | −7,9% | −60% | rilancio dopo la fase 1: identico (50.459,29 €) |

## 11. Promemoria

- Le liste dei titoli sono quelle di oggi (*survivorship bias*): ogni risultato positivo è ottimistico.
- Fisco: le plusvalenze sugli ETF non si compensano con le minusvalenze. Le varianti su ETF sono quindi svantaggiate per un privato italiano e restano fuori da questo ciclo.
- Non modificare P5 dal vivo né le altre strategie durante questo lavoro.
