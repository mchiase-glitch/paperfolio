# P5 V0 — C-attuale

*Modifica rispetto a V0:* nessuna modifica (riferimento). Parametri: `{"backtest_options": {"costs": "current"}}`.
Periodo 01/01/2010–25/11/2026, 100.000 € iniziali; prova fino al 31/12/2018, verifica dal 1/1/2019. Solo dati già in cache.

## Risultati

| | Totale | Prova 2010–2018 | Verifica 2019–2026 |
|---|---|---|---|
| Rendimento annuo netto | -4,0% | -0,4% | -7,9% |

- Valore finale (netto se si vendesse tutto): 50.459 €
- Volatilità annua 13,9%, perdita massima -60,0%, Sharpe -0,36
- Acquisti 3.584, rotazione annua 43,0 volte il capitale
- Giorni con il freno sul drawdown acceso: 1.421
- Ordini non eseguiti: 1

## Costi e imposte

- Commissioni 142.490 €, Tobin tax 10.929 €
- Imposte 15.559 € (plusvalenze 9.060 €, dividendi con ritenute 6.499 €), bollo 1.763 €

## Operazioni

- Operazioni chiuse 3.584 (posizioni ancora aperte alla fine: 0, escluse)
- Rendimento lordo medio per operazione +0,27%, mediano +0,67%
- Costo medio per giro +0,35% (commissioni, Tobin, spread di cambio, slippage)

### Per motivo di uscita

| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |
|---|---|---|---|---|
| sopra la media a 5 (rimbalzo) | 3.047 | +0,93% | 172 € | 71% |
| sotto la media a 200 | 514 | -3,35% | -620 € | 8% |
| stop temporale 10 giorni | 23 | -6,11% | -1.024 € | 0% |

### Per mercato

| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |
|---|---|---|---|---|---|
| Europa | 816 | +0,33% | 49.962 € | 40.792 € | +0,28% |
| Italia | 664 | +0,13% | 19.271 € | 31.866 € | +0,27% |
| USA | 2.104 | +0,29% | 112.307 € | 160.065 € | +0,41% |

Dettaglio di ogni operazione: `P5_V0_C-attuale.csv`.
