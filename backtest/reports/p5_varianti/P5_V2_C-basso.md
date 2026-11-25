# P5 V2 — C-basso

*Modifica rispetto a V0:* senza uscita sotto la media a 200. Parametri: `{"exit_below_sma_long": false, "backtest_options": {"costs": "low"}}`.
Periodo 01/01/2010–25/11/2026, 100.000 € iniziali; prova fino al 31/12/2018, verifica dal 1/1/2019. Solo dati già in cache.

**Costi C-basso:** 0,025% per lato senza parte fissa, minimo 1 €; conto multivaluta senza spread di cambio su operazioni e dividendi (la conversione iniziale unica non è addebitata); Tobin tax e imposte invariate.

## Risultati

| | Totale | Prova 2010–2018 | Verifica 2019–2026 |
|---|---|---|---|
| Rendimento annuo netto | +7,5% | +11,2% | +3,4% |

- Valore finale (netto se si vendesse tutto): 341.010 €
- Volatilità annua 15,4%, perdita massima -33,4%, Sharpe 0,41
- Acquisti 3.794, rotazione annua 45,0 volte il capitale
- Giorni con il freno sul drawdown acceso: 760
- Ordini non eseguiti: 2

## Costi e imposte

- Commissioni 90.159 €, Tobin tax 33.001 €
- Imposte 130.191 € (plusvalenze 110.522 €, dividendi con ritenute 19.669 €), bollo 5.493 €

## Operazioni

- Operazioni chiuse 3.789 (posizioni ancora aperte alla fine: 5, escluse)
- Rendimento lordo medio per operazione +0,31%, mediano +0,75%
- Costo medio per giro +0,07% (commissioni, Tobin, spread di cambio, slippage)

### Per motivo di uscita

| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |
|---|---|---|---|---|
| sopra la media a 5 (rimbalzo) | 3.709 | +0,52% | 226 € | 66% |
| stop temporale 10 giorni | 80 | -9,29% | -4.850 € | 0% |

### Per mercato

| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |
|---|---|---|---|---|---|
| Europa | 881 | +0,47% | 191.037 € | 21.027 € | +0,05% |
| Italia | 729 | +0,13% | 3.320 € | 50.850 € | +0,14% |
| USA | 2.179 | +0,31% | 256.144 € | 50.994 € | +0,05% |

Dettaglio di ogni operazione: `P5_V2_C-basso.csv`.
