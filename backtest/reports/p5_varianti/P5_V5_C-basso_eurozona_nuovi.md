# P5 V5 (eurozona_nuovi) — C-basso

*Modifica rispetto a V0:* V1 + V2 + V3. Parametri: `{"exit_below_sma_long": false, "drawdown_brake": false, "universe_lists": ["eurozona_nuovi"], "backtest_options": {"execution": "close", "slippage": 0.0005, "costs": "low"}}`.
Periodo 01/01/2010–25/11/2026, 100.000 € iniziali; prova fino al 31/12/2018, verifica dal 1/1/2019. Solo dati già in cache.

**Esecuzione:** alla chiusura del giorno del segnale (approssima un ordine al prezzo di chiusura inviato poco prima della fine della seduta), con **slippage dello 0,05% per lato** a sfavore.

**Costi C-basso:** 0,025% per lato senza parte fissa, minimo 1 €; conto multivaluta senza spread di cambio su operazioni e dividendi (la conversione iniziale unica non è addebitata); Tobin tax e imposte invariate.

## Risultati

| | Totale | Prova 2010–2018 | Verifica 2019–2026 |
|---|---|---|---|
| Rendimento annuo netto | -0,8% | +8,9% | -10,7% |

- Valore finale (netto se si vendesse tutto): 87.446 €
- Volatilità annua 16,9%, perdita massima -65,3%, Sharpe -0,08
- Acquisti 4.164, rotazione annua 48,5 volte il capitale
- Giorni con il freno sul drawdown acceso: 0
- Ordini non eseguiti: 0

## Costi e imposte

- Commissioni 57.865 €, Tobin tax 0 €
- Imposte 61.965 € (plusvalenze 36.386 €, dividendi con ritenute 25.579 €), bollo 3.548 €

## Operazioni

- Operazioni chiuse 4.159 (posizioni ancora aperte alla fine: 5, escluse)
- Rendimento lordo medio per operazione +0,18%, mediano +0,82%
- Costo medio per giro +0,15% (commissioni, Tobin, spread di cambio, slippage)

### Per motivo di uscita

| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |
|---|---|---|---|---|
| sopra la media a 5 (rimbalzo) | 4.000 | +0,57% | 154 € | 69% |
| stop temporale 10 giorni | 159 | -9,72% | -2.798 € | 0% |

### Per mercato

| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |
|---|---|---|---|---|---|
| Europa | 4.159 | +0,18% | 171.126 € | 173.525 € | +0,15% |

Dettaglio di ogni operazione: `P5_V5_C-basso_eurozona_nuovi.csv`.
