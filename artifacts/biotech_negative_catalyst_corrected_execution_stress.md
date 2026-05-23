# Biotech Catalyst Execution Stress Report

This report stresses biotech catalyst strategy trades without retuning thresholds or changing labels.

- strategy trades: 61
- next-open stress trades: 61
- next-open note: Intraday SEC-acceptance events are conservatively shifted to the next trading day's open because local data is daily OHLC only.

## Close-To-Close Cost Stress

| all-in cost bps | trades | long | short | mean net | median net | hit rate | cumulative net | max drawdown |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5.0 | 61 | 0 | 61 | 0.08519008388659752 | 0.045719975299539584 | 0.7049180327868853 | 7.632486901888459 | -0.9455162673205515 |
| 25.0 | 61 | 0 | 61 | 0.0831900838865975 | 0.04371997529953958 | 0.6721311475409836 | 6.437150997111882 | -0.9475162673205515 |
| 50.0 | 61 | 0 | 61 | 0.08069008388659753 | 0.04121997529953959 | 0.6721311475409836 | 5.158456379229774 | -0.9500162673205516 |
| 100.0 | 61 | 0 | 61 | 0.07569008388659752 | 0.03621997529953958 | 0.639344262295082 | 3.185874870207389 | -0.9550162673205516 |

## Next-Open Execution Stress

| all-in cost bps | trades | long | short | mean net | median net | hit rate | cumulative net | max drawdown |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5.0 | 61 | 0 | 61 | -0.002389230895686007 | 0.0038477638603404145 | 0.5737704918032787 | -0.2690610284486399 | -0.5712654584090048 |
| 25.0 | 61 | 0 | 61 | -0.004389230895686009 | 0.0018477638603404145 | 0.5409836065573771 | -0.35372350320470336 | -0.6101484315663679 |
| 50.0 | 61 | 0 | 61 | -0.0068892308956860085 | -0.0006522361396595856 | 0.4918032786885246 | -0.44609290017770953 | -0.6554485326661026 |
| 100.0 | 61 | 0 | 61 | -0.01188923089568601 | -0.005652236139659586 | 0.45901639344262296 | -0.5935933579497712 | -0.7321212932689835 |

## Liquidity And Gap Risk

- events audited: None
- medium/high liquidity or execution risk rows: None
- high liquidity or execution risk rows: None
- price under $5 rows: None
- price under $1 rows: None
- absolute opening gap >= 20% rows: None
- low dollar-volume rows: None

Daily OHLC files do not identify exchange trading halts or executable intraday liquidity. Rows with clinical-hold language are risk flags, not proof of exchange trading halts.