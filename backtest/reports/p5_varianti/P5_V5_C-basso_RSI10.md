# P5 V5 RSI<10 — C-basso

*Modifica rispetto a V0:* V1 + V2 + V3. Parametri: `{"exit_below_sma_long": false, "drawdown_brake": false, "rsi_entry": 10, "backtest_options": {"execution": "close", "slippage": 0.0005, "costs": "low"}}`.
Periodo 01/01/2010–25/11/2026, 100.000 € iniziali; prova fino al 31/12/2018, verifica dal 1/1/2019. Solo dati già in cache.

**Esecuzione:** alla chiusura del giorno del segnale (approssima un ordine al prezzo di chiusura inviato poco prima della fine della seduta), con **slippage dello 0,05% per lato** a sfavore.

**Costi C-basso:** 0,025% per lato senza parte fissa, minimo 1 €; conto multivaluta senza spread di cambio su operazioni e dividendi (la conversione iniziale unica non è addebitata); Tobin tax e imposte invariate.

## Risultati

| | Totale | Prova 2010–2018 | Verifica 2019–2026 |
|---|---|---|---|
| Rendimento annuo netto | +10,3% | +13,2% | +6,9% |

- Valore finale (netto se si vendesse tutto): 520.869 €
- Volatilità annua 17,6%, perdita massima -44,3%, Sharpe 0,52
- Acquisti 4.553, rotazione annua 54,0 volte il capitale
- Giorni con il freno sul drawdown acceso: 0
- Ordini non eseguiti: 0

## Costi e imposte

- Commissioni 138.916 €, Tobin tax 50.889 €
- Imposte 218.406 € (plusvalenze 187.143 €, dividendi con ritenute 31.263 €), bollo 8.437 €

## Operazioni

- Operazioni chiuse 4.548 (posizioni ancora aperte alla fine: 5, escluse)
- Rendimento lordo medio per operazione +0,44%, mediano +0,92%
- Costo medio per giro +0,17% (commissioni, Tobin, spread di cambio, slippage)

### Per motivo di uscita

| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |
|---|---|---|---|---|
| sopra la media a 5 (rimbalzo) | 4.402 | +0,72% | 424 € | 70% |
| stop temporale 10 giorni | 146 | -8,16% | -5.679 € | 1% |

### Per mercato

| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |
|---|---|---|---|---|---|
| Europa | 1.062 | +0,55% | 353.047 € | 98.465 € | +0,15% |
| Italia | 849 | +0,12% | 46.973 € | 133.422 € | +0,24% |
| USA | 2.637 | +0,49% | 637.802 € | 235.047 € | +0,15% |

Dettaglio di ogni operazione: `P5_V5_C-basso_RSI10.csv`.
