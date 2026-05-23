# Government Contract Parser Audit Report

This validates parser facts against a reviewed gold set. It is a parser-quality report, not a model result.

## Metrics

- gold_rows: 540
- gold_events: 60
- reviewed_gold_rows: 540
- reviewed_gold_events: 60
- correct_rows: 540
- row_accuracy: 1.000
- parser_audit_pass: True

## Audit Gates

- gold_set_60_rows: PASS
- gold_set_human_reviewed: PASS
- event_type_precision_95: PASS
- recipient_ticker_mapping_precision_90: PASS
- award_and_obligated_amount_precision_95: PASS
- ceiling_vs_funded_distinction_precision_95: PASS
- option_modification_precision_90: PASS
- no_idiq_ceiling_mistaken_for_funded: PASS

## By Fact

- actual_funded_award_flag: {'gold_rows': 60, 'correct': 60, 'precision_on_gold': 1.0}
- award_amount: {'gold_rows': 60, 'correct': 60, 'precision_on_gold': 1.0}
- ceiling_only_flag: {'gold_rows': 60, 'correct': 60, 'precision_on_gold': 1.0}
- contract_ceiling: {'gold_rows': 9, 'correct': 9, 'precision_on_gold': 1.0}
- government_contract_event_type: {'gold_rows': 60, 'correct': 60, 'precision_on_gold': 1.0}
- mapped_ticker: {'gold_rows': 60, 'correct': 60, 'precision_on_gold': 1.0}
- modification_flag: {'gold_rows': 60, 'correct': 60, 'precision_on_gold': 1.0}
- obligated_amount: {'gold_rows': 51, 'correct': 51, 'precision_on_gold': 1.0}
- option_exercise_flag: {'gold_rows': 60, 'correct': 60, 'precision_on_gold': 1.0}
- recipient_mapping_confidence: {'gold_rows': 60, 'correct': 60, 'precision_on_gold': 1.0}
