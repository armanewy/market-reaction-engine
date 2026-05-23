# Biotech Catalyst Parser Audit Report

This validates parser facts against a human-reviewed gold set. It is a parser-quality report, not a model result.

## Metrics

- gold_rows: 60
- correct_rows: 55
- row_accuracy: 0.917
- event_type_precision: 0.886
- drug_asset_indication_precision: 1.000
- trial_phase_precision: 1.000
- endpoint_success_failure_precision: 1.000
- endpoint_statistical_precision: 1.000
- regulatory_decision_precision: 1.000
- parser_audit_pass: False

## Gates

- gold_rows_60: PASS
- event_type_precision_95: FAIL
- drug_asset_indication_precision_90: PASS
- trial_phase_precision_90: PASS
- endpoint_success_failure_precision_90: PASS
- regulatory_decision_precision_95: PASS
- no_designation_only_event_mistaken_for_approval: PASS
- no_enrollment_update_event_mistaken_for_readout: FAIL
- no_publication_conference_notice_mistaken_for_new_topline_result: FAIL

## By Fact

- drug_asset: {'gold_rows': 3, 'correct': 3, 'precision_on_gold': 1.0}
- endpoint_met: {'gold_rows': 4, 'correct': 4, 'precision_on_gold': 1.0}
- event_type: {'gold_rows': 44, 'correct': 39, 'precision_on_gold': 0.8863636363636364}
- hazard_ratio: {'gold_rows': 1, 'correct': 1, 'precision_on_gold': 1.0}
- overall_survival: {'gold_rows': 1, 'correct': 1, 'precision_on_gold': 1.0}
- p_value: {'gold_rows': 3, 'correct': 3, 'precision_on_gold': 1.0}
- response_rate: {'gold_rows': 1, 'correct': 1, 'precision_on_gold': 1.0}
- trial_phase: {'gold_rows': 3, 'correct': 3, 'precision_on_gold': 1.0}

## Non-OK Rows

- CRSP_8-K_2020-05-11_0001564590-20-023884 / event_type: wrong_value expected=unknown actual=accelerated_approval
- INSM_8-K_2020-10-28_0001104659-20-118757 / event_type: wrong_value expected=unknown actual=accelerated_approval
- RXRX_8-K_2024-11-06_0001601830-24-000195 / event_type: wrong_value expected=phase_2_readout actual=endpoint_success
- FATE_8-K_2020-05-05_0001564590-20-021242 / event_type: wrong_value expected=unknown actual=phase_2_readout
- FATE_8-K_2020-08-19_0001564590-20-040672 / event_type: wrong_value expected=unknown actual=phase_2_readout
