# Capital Raise Clean Slice Readiness V2

This is a repaired-slice readiness report for Agent 2L. It is not a prediction result.

## Decision

model-ready after repair

## Metrics

- candidate rows in timestamp audit: 127
- repaired model-eligible rows: 84
- completed financing rows: 84
- capacity-only rows: 0
- financing_amount_pct_market_cap rows: 84
- discount_to_last_close_pct rows: 76
- market_cap_before_event rows: 84
- estimated_dilution_pct rows: 80
- likely OOS predictions at min_train=40: 44
- focused parser audit rows: 33
- focused parser audit accuracy: 1.000
- tickers represented: 37

## Gates

- 80+ repaired model-eligible rows: PASS
- 60+ completed financing rows: PASS
- 40+ financing_amount_pct_market_cap rows: PASS
- 40+ discount_to_last_close_pct rows: PASS
- 30+ likely OOS predictions with min_train=40: PASS
- focused clean-slice parser audit passes: PASS
- timestamp/session audit passes for model rows: PASS
- duplicate audit passes for model rows: PASS

## Preferred Checks

- 100+ repaired model-eligible rows: FAIL
- 60+ parser audit rows: FAIL

## Timestamp / Dedupe Policy

- before_open rows are eligible for same-trading-day reaction.
- after_close rows are eligible for next-trading-day reaction.
- intraday daily-bar rows are marked ineligible/ambiguous.
- duplicate same-financing documents are excluded unless selected as the primary context-complete source.
