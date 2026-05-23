# Capital Raise Corpus Readiness Report

This is a data-readiness report, not a prediction result.

## Summary

- candidate_rows: 32
- reviewed_usable_rows: 32
- completed_financing_rows: 32
- capacity_only_rows: 0
- ambiguous_or_unreviewed_rows: 0
- rejected_rows: 0
- rows_with_financing_amount_best: 18
- rows_with_price_per_share: 18
- rows_with_discount_to_last_close_pct: 13
- rows_with_market_cap_before_event: 13
- rows_with_financing_amount_pct_market_cap: 7
- rows_with_estimated_dilution_pct: 8
- likely_oos_predictions_min_train: 0
- parser_audit_rows: 33
- parser_audit_accuracy: 1.0
- decision: continue corpus buildout
- reason: readiness gates still failing: reviewed_usable_events_80_min, reviewed_usable_events_100_preferred, completed_financing_events_60, financing_amount_pct_market_cap_rows_40, discount_rows_40, likely_oos_predictions_30, parser_audit_pass

## Gates

- reviewed_usable_events_80_min: FAIL
- reviewed_usable_events_100_preferred: FAIL
- completed_financing_events_60: FAIL
- financing_amount_pct_market_cap_rows_40: FAIL
- discount_rows_40: FAIL
- likely_oos_predictions_30: FAIL
- parser_audit_pass: FAIL

## Top Missing Fields / Gates

- reviewed_usable_events_80_min
- reviewed_usable_events_100_preferred
- completed_financing_events_60
- financing_amount_pct_market_cap_rows_40
- discount_rows_40
- likely_oos_predictions_30
- parser_audit_pass
