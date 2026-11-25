# P5 V1 — C-attuale

*Modifica rispetto a V0:* esecuzione alla chiusura del giorno del segnale, slippage 0,05% per lato. Parametri: `{"backtest_options": {"execution": "close", "slippage": 0.0005, "costs": "current"}}`.
Periodo 01/01/2010–25/11/2026, 100.000 € iniziali; prova fino al 31/12/2018, verifica dal 1/1/2019. Solo dati già in cache.

**Esecuzione:** alla chiusura del giorno del segnale (approssima un ordine al prezzo di chiusura inviato poco prima della fine della seduta), con **slippage dello 0,05% per lato** a sfavore.

## Risultati

| | Totale | Prova 2010–2018 | Verifica 2019–2026 |
|---|---|---|---|
| Rendimento annuo netto | -4,6% | -3,1% | -6,2% |

- Valore finale (netto se si vendesse tutto): 45.511 €
- Volatilità annua 13,8%, perdita massima -63,4%, Sharpe -0,40
- Acquisti 3.564, rotazione annua 43,7 volte il capitale
- Giorni con il freno sul drawdown acceso: 1.460
- Ordini non eseguiti: 0

## Costi e imposte

- Commissioni 129.263 €, Tobin tax 9.246 €
- Imposte 12.330 € (plusvalenze 7.381 €, dividendi con ritenute 4.948 €), bollo 1.507 €

## Operazioni

- Operazioni chiuse 3.564 (posizioni ancora aperte alla fine: 0, escluse)
- Rendimento lordo medio per operazione +0,37%, mediano +0,83%
- Costo medio per giro +0,47% (commissioni, Tobin, spread di cambio, slippage)

### Per motivo di uscita

| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |
|---|---|---|---|---|
| sopra la media a 5 (rimbalzo) | 3.016 | +1,13% | 177 € | 76% |
| sotto la media a 200 | 510 | -3,70% | -576 € | 2% |
| stop temporale 10 giorni | 38 | -5,12% | -762 € | 3% |

### Per mercato

| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |
|---|---|---|---|---|---|
| Europa | 812 | +0,34% | 45.918 € | 50.876 € | +0,40% |
| Italia | 660 | +0,20% | 24.680 € | 37.798 € | +0,37% |
| USA | 2.092 | +0,44% | 139.279 € | 176.135 € | +0,52% |

Dettaglio di ogni operazione: `P5_V1_C-attuale.csv`.
