# Agent 2H Capital Raise Clean Slice Falsification Report

This is a first event-study/falsification result for the narrowed completed common-stock / registered-direct slice. It is not a trading recommendation.

## Input Gate

- selected_slice_rows: 80
- event_study_ok_rows: 79
- parser_audit: 33/33 focused rows correct; completed-common-stock slice 31/31 correct
- selected_slice_gate: PASS

## Pre-Registered Buckets

| bucket | n | mean_car_h1 | median_car_h1 | positive_rate_h1 | mean_car_h3 | median_car_h3 | positive_rate_h3 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| all_ok | 79 | -0.0190 | -0.0103 | 0.4051 | -0.0424 | -0.0335 | 0.3291 |
| H1_discounted_after_runup | 16 | 0.0357 | 0.0117 | 0.6250 | -0.0243 | -0.0420 | 0.2500 |
| H2_large_pct_market_cap | 30 | -0.0292 | -0.0050 | 0.4667 | -0.0590 | -0.0997 | 0.3333 |
| H3_large_and_discounted | 11 | 0.0282 | 0.0103 | 0.6364 | 0.0138 | -0.0010 | 0.4545 |
| H4_runup_no_large_discount | 16 | -0.0336 | -0.0264 | 0.3125 | -0.0327 | -0.0221 | 0.4375 |

## Backtest / Controls

| name | n_predictions | roc_auc | ece | n_trades | mean_net_event_return | cumulative_net_return | hit_rate | null_p_value |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| main | 38 | 0.6994 | 0.1956 | 34 | 0.0448 | 2.7820 | 0.7353 | 0.0060 |
| placebo | 117 | 0.4930 | 0.2391 | 93 | -0.0099 | -0.7576 | 0.4946 | 0.8842 |
| peer | 37 | 0.4848 | 0.3376 | 32 | 0.0080 | 0.2105 | 0.5000 | 0.3194 |

## Verdict

Decision: continue, but require fresh-data confirmation before promotion.

Reason: the main walk-forward run is materially stronger than placebo and peer controls, and the null-shuffle p-value is low. The result is still first-pass and could be sensitive to the small 80-row slice, issuer clustering, parser/review choices, and execution assumptions.

Recommended next run: Agent 2I should expand the same clean slice to 120-150 reviewed events, keep the focused false-positive audit active, and rerun the same pre-registered hypotheses without changing thresholds.
