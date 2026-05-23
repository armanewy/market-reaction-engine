# Agent 4H Government Contract Small/Mid Material Award Diagnostic

Decision: failed / freeze government contracts.

This is a narrow diagnostic only. It does not run a new broad model and does not graduate a signal.

## Structural Thresholds

| threshold | rows | tickers | top ticker | top ticker share | top agency share | top program share | h1 median | h1 sign accuracy | h3 median | h10 median |
|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 0.005 | 18 | 8 | SAIC | 0.222 | 0.889 | 0.056 | 0.0084 | 0.5556 | 0.0088 | 0.0385 |
| 0.010 | 16 | 7 | SAIC | 0.250 | 0.875 | 0.062 | 0.0067 | 0.5000 | 0.0088 | 0.0224 |
| 0.020 | 11 | 7 | SAIC | 0.273 | 0.818 | 0.091 | 0.0176 | 0.5455 | 0.0185 | 0.1084 |
| 0.050 | 6 | 4 | SAIC | 0.500 | 0.833 | 0.167 | 0.0211 | 0.6667 | 0.0375 | 0.1311 |

## Controls

| control | rows | tickers | h1 median | h1 sign accuracy | h3 median | h10 median |
|---|---:|---:|---:|---:|---:|---:|
| large_prime_low_materiality | 114 | 7 | -0.0004 | 0.4825 | -0.0021 | -0.0031 |
| random_placebo | 170 | 18 | 0.0014 | 0.5529 | -0.0007 | 0.0042 |
| shifted_placebo | 105 | 18 | -0.0001 | 0.4952 | -0.0034 | -0.0027 |
| peer_control | 185 | 14 | 0.0002 | 0.5081 | -0.0009 | 0.0008 |

## Robustness

- leave-one-ticker rows: 26
- top-3 outlier trim rows: 12
- structural thresholds passing count/ticker/concentration gate: 0
- robust thresholds: []
- primary reason: No pre-registered small/mid material threshold reached 30 usable rows, 6+ tickers, and top ticker share <= 35%.

## Required Cautions

- Thresholds are the pre-registered 0.5%, 1%, 2%, and 5% market-cap cuts.
- This diagnostic does not tune thresholds based on returns.
- Broad government-contract awards already failed Agent 4G falsification.
- A positive descriptive slice is not a tradable signal without a fresh separately pre-registered corpus expansion.
