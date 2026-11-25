# P5 V4 — C-basso

*Modifica rispetto a V0:* entrata con RSI(2) < 5. Parametri: `{"rsi_entry": 5, "backtest_options": {"costs": "low"}}`.
Periodo 01/01/2010–25/11/2026, 100.000 € iniziali; prova fino al 31/12/2018, verifica dal 1/1/2019. Solo dati già in cache.

**Costi C-basso:** 0,025% per lato senza parte fissa, minimo 1 €; conto multivaluta senza spread di cambio su operazioni e dividendi (la conversione iniziale unica non è addebitata); Tobin tax e imposte invariate.

## Risultati

| | Totale | Prova 2010–2018 | Verifica 2019–2026 |
|---|---|---|---|
| Rendimento annuo netto | +6,2% | +13,1% | -1,2% |

- Valore finale (netto se si vendesse tutto): 277.049 €
- Volatilità annua 13,7%, perdita massima -27,3%, Sharpe 0,35
- Acquisti 3.417, rotazione annua 39,6 volte il capitale
- Giorni con il freno sul drawdown acceso: 686
- Ordini non eseguiti: 1

## Costi e imposte

- Commissioni 82.161 €, Tobin tax 29.936 €
- Imposte 107.756 € (plusvalenze 92.494 €, dividendi con ritenute 15.262 €), bollo 4.382 €

## Operazioni

- Operazioni chiuse 3.412 (posizioni ancora aperte alla fine: 5, escluse)
- Rendimento lordo medio per operazione +0,30%, mediano +0,66%
- Costo medio per giro +0,07% (commissioni, Tobin, spread di cambio, slippage)

### Per motivo di uscita

| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |
|---|---|---|---|---|
| sopra la media a 5 (rimbalzo) | 2.869 | +1,01% | 467 € | 72% |
| sotto la media a 200 | 519 | -3,35% | -1.750 € | 9% |
| stop temporale 10 giorni | 24 | -5,10% | -2.725 € | 4% |

### Per mercato

| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |
|---|---|---|---|---|---|
| Europa | 780 | +0,34% | 97.290 € | 18.698 € | +0,05% |
| Italia | 646 | +0,23% | 48.529 € | 46.188 € | +0,14% |
| USA | 1.986 | +0,31% | 219.518 € | 47.033 € | +0,05% |

Dettaglio di ogni operazione: `P5_V4_C-basso.csv`.
