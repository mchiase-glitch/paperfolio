# P5 V3 — C-basso

*Modifica rispetto a V0:* senza freno sul drawdown. Parametri: `{"drawdown_brake": false, "backtest_options": {"costs": "low"}}`.
Periodo 01/01/2010–25/11/2026, 100.000 € iniziali; prova fino al 31/12/2018, verifica dal 1/1/2019. Solo dati già in cache.

**Costi C-basso:** 0,025% per lato senza parte fissa, minimo 1 €; conto multivaluta senza spread di cambio su operazioni e dividendi (la conversione iniziale unica non è addebitata); Tobin tax e imposte invariate.

## Risultati

| | Totale | Prova 2010–2018 | Verifica 2019–2026 |
|---|---|---|---|
| Rendimento annuo netto | +8,5% | +13,4% | +3,1% |

- Valore finale (netto se si vendesse tutto): 398.124 €
- Volatilità annua 17,5%, perdita massima -46,0%, Sharpe 0,43
- Acquisti 5.162, rotazione annua 60,8 volte il capitale
- Giorni con il freno sul drawdown acceso: 0
- Ordini non eseguiti: 0

## Costi e imposte

- Commissioni 141.529 €, Tobin tax 51.648 €
- Imposte 163.222 € (plusvalenze 137.741 €, dividendi con ritenute 25.480 €), bollo 7.521 €

## Operazioni

- Operazioni chiuse 5.157 (posizioni ancora aperte alla fine: 5, escluse)
- Rendimento lordo medio per operazione +0,27%, mediano +0,68%
- Costo medio per giro +0,07% (commissioni, Tobin, spread di cambio, slippage)

### Per motivo di uscita

| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |
|---|---|---|---|---|
| sopra la media a 5 (rimbalzo) | 4.365 | +0,97% | 521 € | 72% |
| sotto la media a 200 | 751 | -3,45% | -2.001 € | 8% |
| stop temporale 10 giorni | 41 | -6,33% | -4.273 € | 0% |

### Per mercato

| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |
|---|---|---|---|---|---|
| Europa | 1.199 | +0,36% | 210.844 € | 33.008 € | +0,05% |
| Italia | 967 | +0,20% | 94.435 € | 79.487 € | +0,14% |
| USA | 2.991 | +0,25% | 290.995 € | 80.347 € | +0,05% |

Dettaglio di ogni operazione: `P5_V3_C-basso.csv`.
