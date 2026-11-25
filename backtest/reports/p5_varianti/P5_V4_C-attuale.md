# P5 V4 — C-attuale

*Modifica rispetto a V0:* entrata con RSI(2) < 5. Parametri: `{"rsi_entry": 5, "backtest_options": {"costs": "current"}}`.
Periodo 01/01/2010–25/11/2026, 100.000 € iniziali; prova fino al 31/12/2018, verifica dal 1/1/2019. Solo dati già in cache.

## Risultati

| | Totale | Prova 2010–2018 | Verifica 2019–2026 |
|---|---|---|---|
| Rendimento annuo netto | -2,4% | +3,2% | -8,5% |

- Valore finale (netto se si vendesse tutto): 66.080 €
- Volatilità annua 13,3%, perdita massima -61,1%, Sharpe -0,26
- Acquisti 3.201, rotazione annua 38,1 volte il capitale
- Giorni con il freno sul drawdown acceso: 966
- Ordini non eseguiti: 1

## Costi e imposte

- Commissioni 147.541 €, Tobin tax 12.562 €
- Imposte 30.360 € (plusvalenze 23.572 €, dividendi con ritenute 6.787 €), bollo 1.975 €

## Operazioni

- Operazioni chiuse 3.196 (posizioni ancora aperte alla fine: 5, escluse)
- Rendimento lordo medio per operazione +0,31%, mediano +0,64%
- Costo medio per giro +0,34% (commissioni, Tobin, spread di cambio, slippage)

### Per motivo di uscita

| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |
|---|---|---|---|---|
| sopra la media a 5 (rimbalzo) | 2.700 | +1,00% | 227 € | 72% |
| sotto la media a 200 | 472 | -3,35% | -761 € | 8% |
| stop temporale 10 giorni | 24 | -4,91% | -1.100 € | 4% |

### Per mercato

| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |
|---|---|---|---|---|---|
| Europa | 737 | +0,32% | 51.732 € | 41.644 € | +0,25% |
| Italia | 606 | +0,13% | 21.234 € | 35.700 € | +0,26% |
| USA | 1.853 | +0,37% | 154.582 € | 168.944 € | +0,40% |

Dettaglio di ogni operazione: `P5_V4_C-attuale.csv`.
