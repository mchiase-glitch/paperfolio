# P5 V5 RSI<15 — C-basso

*Modifica rispetto a V0:* V1 + V2 + V3. Parametri: `{"exit_below_sma_long": false, "drawdown_brake": false, "rsi_entry": 15, "backtest_options": {"execution": "close", "slippage": 0.0005, "costs": "low"}}`.
Periodo 01/01/2010–25/11/2026, 100.000 € iniziali; prova fino al 31/12/2018, verifica dal 1/1/2019. Solo dati già in cache.

**Esecuzione:** alla chiusura del giorno del segnale (approssima un ordine al prezzo di chiusura inviato poco prima della fine della seduta), con **slippage dello 0,05% per lato** a sfavore.

**Costi C-basso:** 0,025% per lato senza parte fissa, minimo 1 €; conto multivaluta senza spread di cambio su operazioni e dividendi (la conversione iniziale unica non è addebitata); Tobin tax e imposte invariate.

## Risultati

| | Totale | Prova 2010–2018 | Verifica 2019–2026 |
|---|---|---|---|
| Rendimento annuo netto | +11,6% | +14,4% | +8,5% |

- Valore finale (netto se si vendesse tutto): 640.329 €
- Volatilità annua 18,3%, perdita massima -50,6%, Sharpe 0,57
- Acquisti 4.961, rotazione annua 58,4 volte il capitale
- Giorni con il freno sul drawdown acceso: 0
- Ordini non eseguiti: 0

## Costi e imposte

- Commissioni 168.236 €, Tobin tax 60.723 €
- Imposte 274.615 € (plusvalenze 234.630 €, dividendi con ritenute 39.985 €), bollo 10.177 €

## Operazioni

- Operazioni chiuse 4.956 (posizioni ancora aperte alla fine: 5, escluse)
- Rendimento lordo medio per operazione +0,44%, mediano +0,90%
- Costo medio per giro +0,17% (commissioni, Tobin, spread di cambio, slippage)

### Per motivo di uscita

| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |
|---|---|---|---|---|
| sopra la media a 5 (rimbalzo) | 4.805 | +0,71% | 472 € | 70% |
| stop temporale 10 giorni | 151 | -8,15% | -6.423 € | 1% |

### Per mercato

| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |
|---|---|---|---|---|---|
| Europa | 1.136 | +0,47% | 374.416 € | 118.019 € | +0,15% |
| Italia | 910 | +0,18% | 103.324 € | 158.643 € | +0,24% |
| USA | 2.910 | +0,52% | 818.283 € | 287.776 € | +0,15% |

Dettaglio di ogni operazione: `P5_V5_C-basso_RSI15.csv`.
