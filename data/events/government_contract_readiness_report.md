# Government Contract Awards Readiness Report

This is a data-readiness report, not a prediction result.

## One-Page Verdict

- verdict: model-ready
- reason: all non-modeling readiness gates pass

## Summary Counts

- source_documents_recovered: 1562
- parsed_event_rows: 186
- reviewed_usable_rows: 186
- actual_funded_award_rows: 186
- ceiling_only_rows: 0
- modification_or_option_rows: 11
- rows_with_recipient_mapping_confidence_high: 186
- rows_with_award_amount_pct_market_cap: 186
- rows_with_obligated_amount_pct_market_cap: 186
- rows_with_contract_ceiling_pct_market_cap: 0
- rows_with_pre_event_market_adjusted_runup: 186
- small_mid_cap_rows: 38
- likely_oos_predictions_min_train: 146
- top_ticker_share: 0.1989247311827957
- parser_audit_rows: 540
- parser_audit_accuracy: 1.0

## Gates

- reviewed_usable_events_80_min: PASS
- reviewed_usable_events_100_preferred: PASS
- actual_funded_award_events_60: PASS
- amount_or_obligation_pct_market_cap_rows_40: PASS
- small_mid_cap_rows_30: PASS
- mapping_high_confidence_rows_80: PASS
- clear_event_timestamps: PASS
- likely_oos_predictions_30: PASS
- pre_event_runup_rows_40: PASS
- parser_audit_pass: PASS

## Top Missing Fields / Gates Blocking Modeling


## Ticker Concentration

- RTX: 37
- LMT: 33
- HII: 24
- BA: 20
- NOC: 20
- GD: 18
- LHX: 6
- AVAV: 5
- CACI: 5
- SAIC: 4

## Pre-Registered Candidate Hypotheses

1. small/mid-cap company AND actual_funded_award_flag = true AND obligated_amount_pct_market_cap >= 5% -> expected positive abnormal return.
2. contract_ceiling_only_flag = true -> expected weaker/noisier reaction than actual funded awards.
3. new_work_flag = true AND award_amount_pct_market_cap >= 5% -> expected stronger positive reaction than modification/option-extension awards.
4. large prime contractor AND award_amount_pct_market_cap < 1% -> expected no meaningful abnormal return.
5. positive pre-event run-up before award announcement -> expected weaker reaction or possible sell-the-news if anticipated.
