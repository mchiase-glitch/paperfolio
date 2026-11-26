# P5 V0 (eurozona_nuovi) — C-basso

*Modifica rispetto a V0:* nessuna modifica (riferimento). Parametri: `{"universe_lists": ["eurozona_nuovi"], "backtest_options": {"costs": "low"}}`.
Periodo 01/01/2010–25/11/2026, 100.000 € iniziali; prova fino al 31/12/2018, verifica dal 1/1/2019. Solo dati già in cache.

**Costi C-basso:** 0,025% per lato senza parte fissa, minimo 1 €; conto multivaluta senza spread di cambio su operazioni e dividendi (la conversione iniziale unica non è addebitata); Tobin tax e imposte invariate.

## Risultati

| | Totale | Prova 2010–2018 | Verifica 2019–2026 |
|---|---|---|---|
| Rendimento annuo netto | +5,9% | +10,9% | +0,5% |

- Valore finale (netto se si vendesse tutto): 262.986 €
- Volatilità annua 14,6%, perdita massima -43,1%, Sharpe 0,32
- Acquisti 4.186, rotazione annua 49,4 volte il capitale
- Giorni con il freno sul drawdown acceso: 593
- Ordini non eseguiti: 0

## Costi e imposte

- Commissioni 74.347 €, Tobin tax 0 €
- Imposte 80.264 € (plusvalenze 52.092 €, dividendi con ritenute 28.172 €), bollo 3.963 €

## Operazioni

- Operazioni chiuse 4.181 (posizioni ancora aperte alla fine: 5, escluse)
- Rendimento lordo medio per operazione +0,21%, mediano +0,69%
- Costo medio per giro +0,05% (commissioni, Tobin, spread di cambio, slippage)

### Per motivo di uscita

| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |
|---|---|---|---|---|
| sopra la media a 5 (rimbalzo) | 3.480 | +1,02% | 354 € | 73% |
| sotto la media a 200 | 672 | -3,71% | -1.365 € | 5% |
| stop temporale 10 giorni | 29 | -5,93% | -2.186 € | 0% |

### Per mercato

| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |
|---|---|---|---|---|---|
| Europa | 4.181 | +0,21% | 252.790 € | 74.283 € | +0,05% |

Dettaglio di ogni operazione: `P5_V0_C-basso_eurozona_nuovi.csv`.
