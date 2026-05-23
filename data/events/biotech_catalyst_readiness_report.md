# Biotech FDA / Clinical Catalyst Readiness Report

This is a data-readiness report, not a prediction result.

## Verdict

- decision: parser not trusted
- reason: parser audit is missing or below gate

## Required Counts

- source_documents_recovered: 2247
- parsed_event_rows: 931
- reviewed_usable_rows: 112
- binary_catalyst_rows: 98
- fda_regulatory_decision_rows: 50
- phase_2_3_readout_rows: 23
- negative_catalyst_rows: 44
- positive_catalyst_rows: 48
- rows_with_market_cap_context: 112
- rows_with_pre_event_runup_context: 112
- rows_with_source_evidence: 112
- parser_audit_precision: 0.9166666666666666
- parser_event_type_precision: 0.8863636363636364
- parser_enrollment_update_false_readout: True
- parser_publication_notice_false_readout: True
- likely_oos_predictions_min_train: 72

## Gates

- reviewed_usable_events_80_min: PASS
- reviewed_usable_events_100_preferred: PASS
- binary_catalyst_events_60: PASS
- negative_catalyst_events_30: PASS
- positive_catalyst_events_30: PASS
- market_cap_context_rows_40: PASS
- pre_event_runup_context_rows_40: PASS
- event_timestamps_clear: PASS
- likely_oos_predictions_30: PASS
- placebo_peer_controls_ready: PASS
- parser_audit_pass: FAIL

## Top Missing Fields Blocking Modeling

- parser_audit_pass

## Pre-Registered Candidate Hypotheses

1. Small/mid-cap biotech, binary negative catalyst: expected negative abnormal return.
2. Phase 3 or pivotal readout with endpoint met and no major safety issue: expected positive abnormal return, strongest for pipeline-concentrated companies.
3. Complete response letter, trial halt, or endpoint failure: expected negative abnormal return.
4. Designation-only events: expected weaker/noisier reaction than approvals/readouts.
5. Positive catalyst after strong pre-event run-up: expected weaker reaction or sell-the-news risk.

Do not model until every gate above passes and placebo/peer controls can be built.
