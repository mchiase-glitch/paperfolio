# P5 V5 — C-attuale

*Modifica rispetto a V0:* V1 + V2 + V3. Parametri: `{"exit_below_sma_long": false, "drawdown_brake": false, "backtest_options": {"execution": "close", "slippage": 0.0005, "costs": "current"}}`.
Periodo 01/01/2010–25/11/2026, 100.000 € iniziali; prova fino al 31/12/2018, verifica dal 1/1/2019. Solo dati già in cache.

**Esecuzione:** alla chiusura del giorno del segnale (approssima un ordine al prezzo di chiusura inviato poco prima della fine della seduta), con **slippage dello 0,05% per lato** a sfavore.

## Risultati

| | Totale | Prova 2010–2018 | Verifica 2019–2026 |
|---|---|---|---|
| Rendimento annuo netto | -1,7% | +1,6% | -5,5% |

- Valore finale (netto se si vendesse tutto): 74.677 €
- Volatilità annua 17,5%, perdita massima -59,4%, Sharpe -0,12
- Acquisti 4.553, rotazione annua 53,0 volte il capitale
- Giorni con il freno sul drawdown acceso: 0
- Ordini non eseguiti: 0

## Costi e imposte

- Commissioni 199.697 €, Tobin tax 16.512 €
- Imposte 31.347 € (plusvalenze 20.940 €, dividendi con ritenute 10.407 €), bollo 2.942 €

## Operazioni

- Operazioni chiuse 4.548 (posizioni ancora aperte alla fine: 5, escluse)
- Rendimento lordo medio per operazione +0,44%, mediano +0,92%
- Costo medio per giro +0,44% (commissioni, Tobin, spread di cambio, slippage)

### Per motivo di uscita

| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |
|---|---|---|---|---|
| sopra la media a 5 (rimbalzo) | 4.402 | +0,72% | 148 € | 70% |
| stop temporale 10 giorni | 146 | -8,16% | -1.670 € | 1% |

### Per mercato

| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |
|---|---|---|---|---|---|
| Europa | 1.062 | +0,55% | 116.638 € | 80.288 € | +0,36% |
| Italia | 849 | +0,12% | 26.991 € | 64.856 € | +0,36% |
| USA | 2.637 | +0,49% | 266.114 € | 283.590 € | +0,50% |

Dettaglio di ogni operazione: `P5_V5_C-attuale.csv`.
