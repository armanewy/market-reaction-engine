# Biotech Catalyst Execution Stress Report

This report stresses Agent 3D strategy trades without retuning thresholds or changing labels.

- strategy trades: 61
- next-open stress trades: 61
- next-open note: Intraday SEC-acceptance events are conservatively shifted to the next trading day's open because local data is daily OHLC only.

## Close-To-Close Cost Stress

| all-in cost bps | trades | long | short | mean net | median net | hit rate | cumulative net | max drawdown |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5.0 | 61 | 0 | 61 | 0.07847988111591327 | 0.049070536132868436 | 0.7049180327868853 | 5.606463469332665 | -0.9455162673205515 |
| 25.0 | 61 | 0 | 61 | 0.07647988111591324 | 0.047070536132868435 | 0.6721311475409836 | 4.689763931494242 | -0.9475162673205515 |
| 50.0 | 61 | 0 | 61 | 0.07397988111591326 | 0.04457053613286844 | 0.6721311475409836 | 3.7095262673281137 | -0.9500162673205516 |
| 100.0 | 61 | 0 | 61 | 0.06897988111591327 | 0.039570536132868435 | 0.6557377049180327 | 2.1983459458927674 | -0.9550162673205516 |

## Next-Open Execution Stress

| all-in cost bps | trades | long | short | mean net | median net | hit rate | cumulative net | max drawdown |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5.0 | 61 | 0 | 61 | 0.003416618616673813 | 0.007019764999358247 | 0.6065573770491803 | 0.034366997456462656 | -0.4671489967781086 |
| 25.0 | 61 | 0 | 61 | 0.001416618616673811 | 0.005019764999358247 | 0.5737704918032787 | -0.08481298042448548 | -0.5112148351453032 |
| 50.0 | 61 | 0 | 61 | -0.0010833813833261894 | 0.002519764999358247 | 0.5245901639344263 | -0.21494057710203762 | -0.5674093831709495 |
| 100.0 | 61 | 0 | 61 | -0.006083381383326188 | -0.002480235000641753 | 0.47540983606557374 | -0.42299412836071393 | -0.6632831048531819 |

## Liquidity And Gap Risk

- events audited: None
- medium/high liquidity or execution risk rows: None
- high liquidity or execution risk rows: None
- price under $5 rows: None
- price under $1 rows: None
- absolute opening gap >= 20% rows: None
- low dollar-volume rows: None

Daily OHLC files do not identify exchange trading halts or executable intraday liquidity. Rows with clinical-hold language are risk flags, not proof of exchange trading halts.