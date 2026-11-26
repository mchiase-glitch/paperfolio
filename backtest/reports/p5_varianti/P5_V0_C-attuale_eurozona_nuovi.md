# P5 V0 (eurozona_nuovi) — C-attuale

*Modifica rispetto a V0:* nessuna modifica (riferimento). Parametri: `{"universe_lists": ["eurozona_nuovi"], "backtest_options": {"costs": "current"}}`.
Periodo 01/01/2010–25/11/2026, 100.000 € iniziali; prova fino al 31/12/2018, verifica dal 1/1/2019. Solo dati già in cache.

## Risultati

| | Totale | Prova 2010–2018 | Verifica 2019–2026 |
|---|---|---|---|
| Rendimento annuo netto | -1,0% | +3,0% | -5,4% |

- Valore finale (netto se si vendesse tutto): 84.466 €
- Volatilità annua 13,8%, perdita massima -56,1%, Sharpe -0,15
- Acquisti 3.836, rotazione annua 45,9 volte il capitale
- Giorni con il freno sul drawdown acceso: 981
- Ordini non eseguiti: 0

## Costi e imposte

- Commissioni 203.866 €, Tobin tax 0 €
- Imposte 26.237 € (plusvalenze 11.348 €, dividendi con ritenute 14.889 €), bollo 2.128 €

## Operazioni

- Operazioni chiuse 3.831 (posizioni ancora aperte alla fine: 5, escluse)
- Rendimento lordo medio per operazione +0,25%, mediano +0,69%
- Costo medio per giro +0,26% (commissioni, Tobin, spread di cambio, slippage)

### Per motivo di uscita

| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |
|---|---|---|---|---|
| sopra la media a 5 (rimbalzo) | 3.208 | +1,01% | 205 € | 73% |
| sotto la media a 200 | 596 | -3,57% | -743 € | 5% |
| stop temporale 10 giorni | 27 | -5,72% | -1.264 € | 0% |

### Per mercato

| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |
|---|---|---|---|---|---|
| Europa | 3.831 | +0,25% | 181.106 € | 203.748 € | +0,26% |

Dettaglio di ogni operazione: `P5_V0_C-attuale_eurozona_nuovi.csv`.
