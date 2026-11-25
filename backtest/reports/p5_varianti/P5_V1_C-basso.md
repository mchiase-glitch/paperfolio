# P5 V1 — C-basso

*Modifica rispetto a V0:* esecuzione alla chiusura del giorno del segnale, slippage 0,05% per lato. Parametri: `{"backtest_options": {"execution": "close", "slippage": 0.0005, "costs": "low"}}`.
Periodo 01/01/2010–25/11/2026, 100.000 € iniziali; prova fino al 31/12/2018, verifica dal 1/1/2019. Solo dati già in cache.

**Esecuzione:** alla chiusura del giorno del segnale (approssima un ordine al prezzo di chiusura inviato poco prima della fine della seduta), con **slippage dello 0,05% per lato** a sfavore.

**Costi C-basso:** 0,025% per lato senza parte fissa, minimo 1 €; conto multivaluta senza spread di cambio su operazioni e dividendi (la conversione iniziale unica non è addebitata); Tobin tax e imposte invariate.

## Risultati

| | Totale | Prova 2010–2018 | Verifica 2019–2026 |
|---|---|---|---|
| Rendimento annuo netto | +6,2% | +8,6% | +3,4% |

- Valore finale (netto se si vendesse tutto): 276.615 €
- Volatilità annua 15,2%, perdita massima -26,7%, Sharpe 0,33
- Acquisti 4.369, rotazione annua 51,9 volte il capitale
- Giorni con il freno sul drawdown acceso: 764
- Ordini non eseguiti: 0

## Costi e imposte

- Commissioni 85.589 €, Tobin tax 31.015 €
- Imposte 100.156 € (plusvalenze 83.897 €, dividendi con ritenute 16.258 €), bollo 4.490 €

## Operazioni

- Operazioni chiuse 4.364 (posizioni ancora aperte alla fine: 5, escluse)
- Rendimento lordo medio per operazione +0,35%, mediano +0,82%
- Costo medio per giro +0,17% (commissioni, Tobin, spread di cambio, slippage)

### Per motivo di uscita

| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |
|---|---|---|---|---|
| sopra la media a 5 (rimbalzo) | 3.678 | +1,10% | 430 € | 76% |
| sotto la media a 200 | 642 | -3,64% | -1.502 € | 2% |
| stop temporale 10 giorni | 44 | -4,78% | -1.966 € | 2% |

### Per mercato

| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |
|---|---|---|---|---|---|
| Europa | 1.018 | +0,41% | 149.733 € | 59.853 € | +0,15% |
| Italia | 831 | +0,24% | 53.869 € | 81.561 € | +0,24% |
| USA | 2.515 | +0,36% | 325.891 € | 145.997 € | +0,15% |

Dettaglio di ogni operazione: `P5_V1_C-basso.csv`.
