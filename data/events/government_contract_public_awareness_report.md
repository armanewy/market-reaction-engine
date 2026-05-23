# Government Contract Public Awareness Report

This validates public-announcement links for government-contract events. It is not a model result.

## Verdict

- verdict: continue public-announcement linking

## Summary

- announcement_manifest_rows: 14
- validated_link_rows: 14
- valid_public_announcement_links: 10
- model_eligible_public_rows: 10
- audit_rows: 60
- warning: Public-announcement linking is a data-quality gate only; no model, event study, or backtest was run.

## Gates

- public_announcement_timestamp_precision_95: PASS
- award_to_announcement_link_precision_90: FAIL
- no_usaspending_only_model_eligible: PASS
- no_duplicate_award_counted_twice: PASS
- eligible_public_rows_80_min: FAIL
- eligible_public_rows_100_preferred: FAIL
- likely_oos_predictions_30: FAIL
- parser_audit_pass: PASS

## Audit Status Counts

- usaspending_only_negative_control: 46
- ok: 10
- invalid: 4

## Duplicate Status Counts

- primary: 14
