# P5 V5 (eurozona_nuovi) — C-attuale

*Modifica rispetto a V0:* V1 + V2 + V3. Parametri: `{"exit_below_sma_long": false, "drawdown_brake": false, "universe_lists": ["eurozona_nuovi"], "backtest_options": {"execution": "close", "slippage": 0.0005, "costs": "current"}}`.
Periodo 01/01/2010–25/11/2026, 100.000 € iniziali; prova fino al 31/12/2018, verifica dal 1/1/2019. Solo dati già in cache.

**Esecuzione:** alla chiusura del giorno del segnale (approssima un ordine al prezzo di chiusura inviato poco prima della fine della seduta), con **slippage dello 0,05% per lato** a sfavore.

## Risultati

| | Totale | Prova 2010–2018 | Verifica 2019–2026 |
|---|---|---|---|
| Rendimento annuo netto | -21,6% | +0,5% | -40,9% |

- Valore finale (netto se si vendesse tutto): 1.642 €
- Volatilità annua 16,9%, perdita massima -98,7%, Sharpe -1,45
- Acquisti 4.163, rotazione annua 47,9 volte il capitale
- Giorni con il freno sul drawdown acceso: 0
- Ordini non eseguiti: 0

## Costi e imposte

- Commissioni 182.278 €, Tobin tax 0 €
- Imposte 18.360 € (plusvalenze 5.311 €, dividendi con ritenute 13.049 €), bollo 1.787 €

## Operazioni

- Operazioni chiuse 4.158 (posizioni ancora aperte alla fine: 5, escluse)
- Rendimento lordo medio per operazione +0,18%, mediano +0,81%
- Costo medio per giro +0,67% (commissioni, Tobin, spread di cambio, slippage)

### Per motivo di uscita

| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |
|---|---|---|---|---|
| sopra la media a 5 (rimbalzo) | 3.999 | +0,57% | 85 € | 69% |
| stop temporale 10 giorni | 159 | -9,72% | -1.311 € | 0% |

### Per mercato

| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |
|---|---|---|---|---|---|
| Europa | 4.158 | +0,18% | 131.981 € | 241.092 € | +0,67% |

Dettaglio di ogni operazione: `P5_V5_C-attuale_eurozona_nuovi.csv`.
