# P5 V3 — C-attuale

*Modifica rispetto a V0:* senza freno sul drawdown. Parametri: `{"drawdown_brake": false, "backtest_options": {"costs": "current"}}`.
Periodo 01/01/2010–25/11/2026, 100.000 € iniziali; prova fino al 31/12/2018, verifica dal 1/1/2019. Solo dati già in cache.

## Risultati

| | Totale | Prova 2010–2018 | Verifica 2019–2026 |
|---|---|---|---|
| Rendimento annuo netto | -6,7% | -0,1% | -13,9% |

- Valore finale (netto se si vendesse tutto): 30.968 €
- Volatilità annua 17,5%, perdita massima -76,2%, Sharpe -0,41
- Acquisti 5.163, rotazione annua 59,5 volte il capitale
- Giorni con il freno sul drawdown acceso: 0
- Ordini non eseguiti: 1

## Costi e imposte

- Commissioni 190.392 €, Tobin tax 14.061 €
- Imposte 17.074 € (plusvalenze 9.664 €, dividendi con ritenute 7.410 €), bollo 2.236 €

## Operazioni

- Operazioni chiuse 5.158 (posizioni ancora aperte alla fine: 5, escluse)
- Rendimento lordo medio per operazione +0,27%, mediano +0,68%
- Costo medio per giro +0,37% (commissioni, Tobin, spread di cambio, slippage)

### Per motivo di uscita

| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |
|---|---|---|---|---|
| sopra la media a 5 (rimbalzo) | 4.366 | +0,97% | 157 € | 72% |
| sotto la media a 200 | 751 | -3,45% | -556 € | 8% |
| stop temporale 10 giorni | 41 | -6,33% | -820 € | 0% |

### Per mercato

| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |
|---|---|---|---|---|---|
| Europa | 1.199 | +0,36% | 73.151 € | 56.502 € | +0,31% |
| Italia | 968 | +0,20% | 35.427 € | 41.491 € | +0,28% |
| USA | 2.991 | +0,25% | 126.103 € | 207.097 € | +0,42% |

Dettaglio di ogni operazione: `P5_V3_C-attuale.csv`.
