# P5 V0 — C-basso

*Modifica rispetto a V0:* nessuna modifica (riferimento). Parametri: `{"backtest_options": {"costs": "low"}}`.
Periodo 01/01/2010–25/11/2026, 100.000 € iniziali; prova fino al 31/12/2018, verifica dal 1/1/2019. Solo dati già in cache.

**Costi C-basso:** 0,025% per lato senza parte fissa, minimo 1 €; conto multivaluta senza spread di cambio su operazioni e dividendi (la conversione iniziale unica non è addebitata); Tobin tax e imposte invariate.

## Risultati

| | Totale | Prova 2010–2018 | Verifica 2019–2026 |
|---|---|---|---|
| Rendimento annuo netto | +6,7% | +11,2% | +1,7% |

- Valore finale (netto se si vendesse tutto): 298.284 €
- Volatilità annua 15,3%, perdita massima -30,3%, Sharpe 0,36
- Acquisti 4.381, rotazione annua 51,7 volte il capitale
- Giorni con il freno sul drawdown acceso: 748
- Ordini non eseguiti: 0

## Costi e imposte

- Commissioni 101.535 €, Tobin tax 36.865 €
- Imposte 131.457 € (plusvalenze 112.437 €, dividendi con ritenute 19.020 €), bollo 5.345 €

## Operazioni

- Operazioni chiuse 4.376 (posizioni ancora aperte alla fine: 5, escluse)
- Rendimento lordo medio per operazione +0,26%, mediano +0,66%
- Costo medio per giro +0,07% (commissioni, Tobin, spread di cambio, slippage)

### Per motivo di uscita

| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |
|---|---|---|---|---|
| sopra la media a 5 (rimbalzo) | 3.697 | +0,94% | 426 € | 72% |
| sotto la media a 200 | 653 | -3,37% | -1.651 € | 8% |
| stop temporale 10 giorni | 26 | -5,45% | -2.739 € | 0% |

### Per mercato

| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |
|---|---|---|---|---|---|
| Europa | 1.023 | +0,38% | 161.206 € | 23.662 € | +0,05% |
| Italia | 836 | +0,26% | 76.745 € | 56.835 € | +0,14% |
| USA | 2.517 | +0,21% | 186.613 € | 57.651 € | +0,05% |

Dettaglio di ogni operazione: `P5_V0_C-basso.csv`.
