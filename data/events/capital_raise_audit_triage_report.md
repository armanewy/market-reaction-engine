# Capital Raise Audit Triage and Scope Narrowing

This is a parser/data-readiness report, not a prediction result.

## Decision

- decision: model-ready slice found
- recommendation: narrow first model to A. completed common-stock offerings / registered directs

## Overall Audit

- gold_rows: 33
- correct_rows: 33
- overall_accuracy: 1.000

## Failure Counts By Class


## Failure Counts By Fact Type


## Failure Counts By Event Subtype


## Slice Audit And Coverage

### A. completed common-stock offerings / registered directs

- audit_rows: 31
- audit_correct: 31
- audit_accuracy: 1.000
- audit_pass: PASS
- reviewed_usable_rows: 80
- completed_financing_rows: 80
- financing_amount_pct_market_cap_rows: 69
- discount_to_last_close_pct_rows: 64
- likely_oos_predictions_min_train: 40
- model_slice_gate_pass: PASS

### B. ATM program creation / ATM usage

- audit_rows: 0
- audit_correct: 0
- audit_accuracy: 0.000
- audit_pass: FAIL
- reviewed_usable_rows: 61
- completed_financing_rows: 34
- financing_amount_pct_market_cap_rows: 47
- discount_to_last_close_pct_rows: 20
- likely_oos_predictions_min_train: 21
- model_slice_gate_pass: FAIL

### C. convertible debt

- audit_rows: 1
- audit_correct: 1
- audit_accuracy: 1.000
- audit_pass: PASS
- reviewed_usable_rows: 84
- completed_financing_rows: 83
- financing_amount_pct_market_cap_rows: 68
- discount_to_last_close_pct_rows: 15
- likely_oos_predictions_min_train: 44
- model_slice_gate_pass: FAIL

### D. shelf registrations / prospectus supplements

- audit_rows: 0
- audit_correct: 0
- audit_accuracy: 0.000
- audit_pass: FAIL
- reviewed_usable_rows: 54
- completed_financing_rows: 0
- financing_amount_pct_market_cap_rows: 32
- discount_to_last_close_pct_rows: 21
- likely_oos_predictions_min_train: 14
- model_slice_gate_pass: FAIL

### E. going-concern / liquidity warnings

- audit_rows: 0
- audit_correct: 0
- audit_accuracy: 0.000
- audit_pass: FAIL
- reviewed_usable_rows: 0
- completed_financing_rows: 0
- financing_amount_pct_market_cap_rows: 0
- discount_to_last_close_pct_rows: 0
- likely_oos_predictions_min_train: 0
- model_slice_gate_pass: FAIL

### Other / ambiguous

- audit_rows: 1
- audit_correct: 1
- audit_accuracy: 1.000
- audit_pass: PASS
- reviewed_usable_rows: 1
- completed_financing_rows: 0
- financing_amount_pct_market_cap_rows: 1
- discount_to_last_close_pct_rows: 0
- likely_oos_predictions_min_train: 0
- model_slice_gate_pass: FAIL
