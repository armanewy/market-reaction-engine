# Biotech Catalyst Execution Stress Report

This report stresses Agent 3D strategy trades without retuning thresholds or changing labels.

- strategy trades: 50
- next-open stress trades: 50
- next-open note: Intraday SEC-acceptance events are conservatively shifted to the next trading day's open because local data is daily OHLC only.

## Close-To-Close Cost Stress

| all-in cost bps | trades | long | short | mean net | median net | hit rate | cumulative net | max drawdown |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5.0 | 50 | 18 | 32 | 0.08069081968753469 | 0.023024469882201498 | 0.66 | 31.418078030412772 | -0.190477386453197 |
| 25.0 | 50 | 18 | 32 | 0.07869081968753469 | 0.021024469882201503 | 0.66 | 28.508142742441407 | -0.19889453222645082 |
| 50.0 | 50 | 18 | 32 | 0.07619081968753466 | 0.0185244698822015 | 0.62 | 25.228618298011437 | -0.20931739770483682 |
| 100.0 | 50 | 18 | 32 | 0.07119081968753466 | 0.0135244698822015 | 0.62 | 19.704963972138362 | -0.22983782374243655 |

## Next-Open Execution Stress

| all-in cost bps | trades | long | short | mean net | median net | hit rate | cumulative net | max drawdown |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5.0 | 50 | 18 | 32 | 0.009094561343886415 | 0.006468960925224587 | 0.6 | 0.4685444950684723 | -0.16753848287774376 |
| 25.0 | 50 | 18 | 32 | 0.007094561343886414 | 0.004468960925224587 | 0.58 | 0.3294963623843443 | -0.16953848287774376 |
| 50.0 | 50 | 18 | 32 | 0.004594561343886414 | 0.0019689609252245876 | 0.5 | 0.1737232912093909 | -0.18373516819195523 |
| 100.0 | 50 | 18 | 32 | -0.0004054386561135844 | -0.0030310390747754126 | 0.48 | -0.08606496284669407 | -0.25974805961677017 |

## Liquidity And Gap Risk

- events audited: 97
- medium/high liquidity or execution risk rows: 36
- high liquidity or execution risk rows: 0
- price under $5 rows: 3
- price under $1 rows: 0
- absolute opening gap >= 20% rows: 15
- low dollar-volume rows: 2

Daily OHLC files do not identify exchange trading halts or executable intraday liquidity. Rows with clinical-hold language are risk flags, not proof of exchange trading halts.