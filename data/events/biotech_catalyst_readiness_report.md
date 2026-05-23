# Biotech FDA / Clinical Catalyst Readiness Report

This is a data-readiness report, not a prediction result.

## Verdict

- decision: model-ready
- reason: hard readiness gates pass; reviewed usable rows clear the 80-row minimum but remain below the 100-row preferred target

## Required Counts

- source_documents_recovered: 2247
- parsed_event_rows: 1196
- reviewed_usable_rows: 97
- binary_catalyst_rows: 68
- fda_regulatory_decision_rows: 40
- phase_2_3_readout_rows: 25
- negative_catalyst_rows: 34
- positive_catalyst_rows: 39
- rows_with_market_cap_context: 97
- rows_with_pre_event_runup_context: 97
- rows_with_source_evidence: 97
- parser_audit_precision: 1.0
- parser_event_type_precision: 1.0
- parser_enrollment_update_false_readout: False
- parser_publication_notice_false_readout: False
- parser_hard_negative_false_catalyst: False
- parser_pipeline_table_false_catalyst: False
- likely_oos_predictions_min_train: 57

## Gates

- reviewed_usable_events_80_min: PASS
- reviewed_usable_events_100_preferred: FAIL
- binary_catalyst_events_60: PASS
- negative_catalyst_events_30: PASS
- positive_catalyst_events_30: PASS
- market_cap_context_rows_40: PASS
- pre_event_runup_context_rows_40: PASS
- event_timestamps_clear: PASS
- likely_oos_predictions_30: PASS
- placebo_peer_controls_ready: PASS
- parser_audit_pass: PASS

## Top Missing Fields Blocking Modeling


## Pre-Registered Candidate Hypotheses

1. Small/mid-cap biotech, binary negative catalyst: expected negative abnormal return.
2. Phase 3 or pivotal readout with endpoint met and no major safety issue: expected positive abnormal return, strongest for pipeline-concentrated companies.
3. Complete response letter, trial halt, or endpoint failure: expected negative abnormal return.
4. Designation-only events: expected weaker/noisier reaction than approvals/readouts.
5. Positive catalyst after strong pre-event run-up: expected weaker reaction or sell-the-news risk.

Do not model until every hard gate above passes and placebo/peer controls can be built. The 100-row target is preferred; 80 reviewed usable rows is the minimum gate.
