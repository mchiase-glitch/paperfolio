# P5 V2 — C-attuale

*Modifica rispetto a V0:* senza uscita sotto la media a 200. Parametri: `{"exit_below_sma_long": false, "backtest_options": {"costs": "current"}}`.
Periodo 01/01/2010–25/11/2026, 100.000 € iniziali; prova fino al 31/12/2018, verifica dal 1/1/2019. Solo dati già in cache.

## Risultati

| | Totale | Prova 2010–2018 | Verifica 2019–2026 |
|---|---|---|---|
| Rendimento annuo netto | -3,0% | +0,9% | -7,2% |

- Valore finale (netto se si vendesse tutto): 59.966 €
- Volatilità annua 15,1%, perdita massima -56,8%, Sharpe -0,25
- Acquisti 3.558, rotazione annua 42,6 volte il capitale
- Giorni con il freno sul drawdown acceso: 998
- Ordini non eseguiti: 2

## Costi e imposte

- Commissioni 145.411 €, Tobin tax 11.725 €
- Imposte 20.023 € (plusvalenze 12.485 €, dividendi con ritenute 7.538 €), bollo 2.104 €

## Operazioni

- Operazioni chiuse 3.553 (posizioni ancora aperte alla fine: 5, escluse)
- Rendimento lordo medio per operazione +0,30%, mediano +0,73%
- Costo medio per giro +0,35% (commissioni, Tobin, spread di cambio, slippage)

### Per motivo di uscita

| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |
|---|---|---|---|---|
| sopra la media a 5 (rimbalzo) | 3.476 | +0,51% | 97 € | 66% |
| stop temporale 10 giorni | 77 | -9,30% | -1.774 € | 0% |

### Per mercato

| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |
|---|---|---|---|---|---|
| Europa | 814 | +0,44% | 67.324 € | 41.570 € | +0,28% |
| Italia | 678 | +0,05% | 8.650 € | 33.900 € | +0,27% |
| USA | 2.061 | +0,32% | 124.150 € | 162.730 € | +0,40% |

Dettaglio di ogni operazione: `P5_V2_C-attuale.csv`.
