# Biotech Catalyst Parser Audit Report

This validates parser facts against a human-reviewed gold set. It is a parser-quality report, not a model result.

## Metrics

- gold_rows: 82
- correct_rows: 82
- row_accuracy: 1.000
- event_type_precision: 1.000
- drug_asset_indication_precision: 1.000
- trial_phase_precision: 1.000
- endpoint_success_failure_precision: 1.000
- endpoint_statistical_precision: 1.000
- regulatory_decision_precision: 1.000
- parser_audit_pass: True

## Gates

- gold_rows_60: PASS
- event_type_precision_95: PASS
- drug_asset_indication_precision_90: PASS
- trial_phase_precision_90: PASS
- endpoint_success_failure_precision_90: PASS
- regulatory_decision_precision_95: PASS
- no_designation_only_event_mistaken_for_approval: PASS
- no_enrollment_update_event_mistaken_for_readout: PASS
- no_publication_conference_notice_mistaken_for_new_topline_result: PASS
- no_hard_negative_mistaken_for_binary_catalyst: PASS
- no_investor_deck_pipeline_table_mistaken_for_new_catalyst: PASS
- no_trial_initiation_mistaken_for_readout: PASS
- no_trial_design_protocol_mistaken_for_readout: PASS
- no_previously_announced_result_mistaken_for_new_catalyst: PASS

## By Fact

- drug_asset: {'gold_rows': 4, 'correct': 4, 'precision_on_gold': 1.0}
- endpoint_met: {'gold_rows': 6, 'correct': 6, 'precision_on_gold': 1.0}
- event_type: {'gold_rows': 60, 'correct': 60, 'precision_on_gold': 1.0}
- indication: {'gold_rows': 4, 'correct': 4, 'precision_on_gold': 1.0}
- p_value: {'gold_rows': 4, 'correct': 4, 'precision_on_gold': 1.0}
- trial_phase: {'gold_rows': 4, 'correct': 4, 'precision_on_gold': 1.0}
