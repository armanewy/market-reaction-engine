# Backtest Interpretation

Backtests in this repository are falsification tools. They can reject weak
domains, identify concentration, and expose calibration or execution problems.
They do not prove tradable alpha.

## Main Outputs

Walk-forward predictions are event-by-event probabilities produced from earlier
rows only. Purged walk-forward removes recent overlapping rows from the training
window to reduce reaction-window leakage.

Calibration tables bucket predicted probabilities and compare them with observed
positive rates. Expected calibration error (ECE) is useful for detecting models
that rank events but assign unreliable probabilities.

Strategy simulation applies long/short thresholds, costs, and slippage to
event-level returns. These returns are not annualized and do not include live
liquidity, borrow, halt, or order-book constraints.

Null shuffle tests randomly permute realized event returns to ask whether the
strategy is meaningfully better than chance alignment between predictions and
outcomes.

Placebo controls test non-event dates for the same tickers. Peer controls test
whether similar non-event tickers produce comparable results.

Concentration diagnostics summarize whether a small number of tickers or event
types drive the result. A domain result dominated by a few issuers is not yet a
domain signal.

Nested threshold selection, when enabled, chooses thresholds from prior
prediction rows only. Fixed thresholds remain useful for plumbing diagnostics but
should not be tuned on the final out-of-sample predictions.

## Red Flags

- Too few predictions or trades
- High ECE or unstable calibration bins
- Positive close-to-close results but failed next-open execution
- Strategy return weaker than placebo or peer controls
- Result driven by one ticker or top-five ticker concentration
- Strong metric only after changing thresholds on final OOS rows
- Unknown release sessions or unaudited timestamps
- Missing evidence, weak label quality, or duplicate-risk rows
- Failed fresh confirmation
