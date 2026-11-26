# P5 V5 RSI<5 — C-basso

*Modifica rispetto a V0:* V1 + V2 + V3. Parametri: `{"exit_below_sma_long": false, "drawdown_brake": false, "rsi_entry": 5, "backtest_options": {"execution": "close", "slippage": 0.0005, "costs": "low"}}`.
Periodo 01/01/2010–25/11/2026, 100.000 € iniziali; prova fino al 31/12/2018, verifica dal 1/1/2019. Solo dati già in cache.

**Esecuzione:** alla chiusura del giorno del segnale (approssima un ordine al prezzo di chiusura inviato poco prima della fine della seduta), con **slippage dello 0,05% per lato** a sfavore.

**Costi C-basso:** 0,025% per lato senza parte fissa, minimo 1 €; conto multivaluta senza spread di cambio su operazioni e dividendi (la conversione iniziale unica non è addebitata); Tobin tax e imposte invariate.

## Risultati

| | Totale | Prova 2010–2018 | Verifica 2019–2026 |
|---|---|---|---|
| Rendimento annuo netto | +7,1% | +11,9% | +1,8% |

- Valore finale (netto se si vendesse tutto): 320.449 €
- Volatilità annua 15,6%, perdita massima -48,4%, Sharpe 0,38
- Acquisti 3.556, rotazione annua 42,2 volte il capitale
- Giorni con il freno sul drawdown acceso: 0
- Ordini non eseguiti: 0

## Costi e imposte

- Commissioni 89.149 €, Tobin tax 33.538 €
- Imposte 126.818 € (plusvalenze 107.550 €, dividendi con ritenute 19.268 €), bollo 5.530 €

## Operazioni

- Operazioni chiuse 3.551 (posizioni ancora aperte alla fine: 5, escluse)
- Rendimento lordo medio per operazione +0,42%, mediano +0,93%
- Costo medio per giro +0,17% (commissioni, Tobin, spread di cambio, slippage)

### Per motivo di uscita

| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |
|---|---|---|---|---|
| sopra la media a 5 (rimbalzo) | 3.433 | +0,69% | 318 € | 70% |
| stop temporale 10 giorni | 118 | -7,36% | -4.091 € | 1% |

### Per mercato

| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |
|---|---|---|---|---|---|
| Europa | 828 | +0,39% | 127.892 € | 62.519 € | +0,15% |
| Italia | 688 | +0,18% | 49.549 € | 87.804 € | +0,24% |
| USA | 2.035 | +0,51% | 431.392 € | 150.292 € | +0,15% |

Dettaglio di ogni operazione: `P5_V5_C-basso_RSI5.csv`.
