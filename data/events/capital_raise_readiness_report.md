# Agent 2G Capital Raise Clean Slice Readiness

This is a slice-readiness report, not a prediction result.

## Decision

- decision: model-ready slice found
- selected_slice: completed common-stock offerings / registered directs
- next_step: Agent 2H first event-study/falsification run is allowed for this slice only.

## Selected Slice Gates

- parser_audit_rows: 31
- parser_audit_correct: 31
- parser_audit_accuracy: 1.000
- reviewed_usable_rows: 80
- completed_financing_rows: 80
- financing_amount_pct_market_cap_rows: 69
- discount_to_last_close_pct_rows: 64
- likely_oos_predictions_min_train_40: 40
- model_slice_gate_pass: PASS

## Notes

- Added 10 Agent 2G source-reviewed rows to the clean slice.
- Expanded focused gold set to 33 audit rows, including 4 negative false-positive checks.
- High-risk guards covered warrant/exercise-price and missing-price false positives; underwriter/pre-funded warrant price selection is covered by source-reviewed positive rows.
- The broad all-domain readiness helper still expects a 60-row whole-domain parser audit; this report is the controlling gate for the narrowed slice.

## Pre-Registered 2H Hypotheses

- H1: discounted offering after run-up: pre_event_market_adjusted_return_20d > 0 and discount_to_last_close_pct <= -10%.
- H2: large financing relative to market cap: financing_amount_pct_market_cap >= 10%.
- H3: combined severity: financing_amount_pct_market_cap >= 10% and discount_to_last_close_pct <= -10%.
- H4: run-up without discount severity should be weaker than discounted run-up offerings.
