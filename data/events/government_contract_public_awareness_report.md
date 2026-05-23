# Government Contract Public Awareness Report

This validates public-announcement links for government-contract events. It is not a model result.

## Verdict

- verdict: model-ready

## Summary

- announcement_manifest_rows: 190
- validated_link_rows: 190
- valid_public_announcement_links: 186
- model_eligible_public_rows: 186
- audit_rows: 60
- warning: Public-announcement linking is a data-quality gate only; no model, event study, or backtest was run.

## Gates

- public_announcement_timestamp_precision_95: PASS
- award_to_announcement_link_precision_90: PASS
- no_usaspending_only_model_eligible: PASS
- no_duplicate_award_counted_twice: PASS
- eligible_public_rows_80_min: PASS
- eligible_public_rows_100_preferred: PASS
- likely_oos_predictions_30: PASS
- parser_audit_pass: PASS

## Audit Status Counts

- ok: 58
- invalid: 2

## Duplicate Status Counts

- primary: 190
