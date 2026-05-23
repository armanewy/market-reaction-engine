# Government Contract Awards Readiness Report

This is a data-readiness report, not a prediction result.

## One-Page Verdict

- verdict: parser not trusted
- reason: parser audit is missing or failing

## Summary Counts

- source_documents_recovered: 1562
- parsed_event_rows: 1554
- reviewed_usable_rows: 0
- actual_funded_award_rows: 1545
- ceiling_only_rows: 9
- modification_or_option_rows: 30
- rows_with_recipient_mapping_confidence_high: 1388
- rows_with_award_amount_pct_market_cap: 1216
- rows_with_obligated_amount_pct_market_cap: 1208
- rows_with_contract_ceiling_pct_market_cap: 10
- rows_with_pre_event_market_adjusted_runup: 1385
- small_mid_cap_rows: 404
- likely_oos_predictions_min_train: 0
- top_ticker_share: 0.0945945945945946
- parser_audit_rows: 540
- parser_audit_accuracy: 0.0

## Gates

- reviewed_usable_events_80_min: FAIL
- reviewed_usable_events_100_preferred: FAIL
- actual_funded_award_events_60: PASS
- amount_or_obligation_pct_market_cap_rows_40: PASS
- small_mid_cap_rows_30: PASS
- mapping_high_confidence_rows_80: PASS
- clear_event_timestamps: FAIL
- likely_oos_predictions_30: FAIL
- pre_event_runup_rows_40: PASS
- parser_audit_pass: FAIL

## Top Missing Fields / Gates Blocking Modeling

- reviewed_usable_events_80_min
- reviewed_usable_events_100_preferred
- clear_event_timestamps
- likely_oos_predictions_30
- parser_audit_pass

## Ticker Concentration

- PLTR: 147
- LHX: 140
- CACI: 108
- BAH: 103
- LDOS: 102
- GD: 97
- NOC: 90
- SAIC: 89
- BA: 88
- LMT: 81

## Pre-Registered Candidate Hypotheses

1. small/mid-cap company AND actual_funded_award_flag = true AND obligated_amount_pct_market_cap >= 5% -> expected positive abnormal return.
2. contract_ceiling_only_flag = true -> expected weaker/noisier reaction than actual funded awards.
3. new_work_flag = true AND award_amount_pct_market_cap >= 5% -> expected stronger positive reaction than modification/option-extension awards.
4. large prime contractor AND award_amount_pct_market_cap < 1% -> expected no meaningful abnormal return.
5. positive pre-event run-up before award announcement -> expected weaker reaction or possible sell-the-news if anticipated.
