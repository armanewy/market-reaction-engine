# Government Contract Parser Audit Report

This validates parser facts against a reviewed gold set. It is a parser-quality report, not a model result.

## Metrics

- gold_rows: 540
- gold_events: 60
- reviewed_gold_rows: 0
- reviewed_gold_events: 0
- correct_rows: 0
- row_accuracy: 0.000
- parser_audit_pass: False

## Audit Gates

- gold_set_60_rows: FAIL
- gold_set_human_reviewed: FAIL
- event_type_precision_95: FAIL
- recipient_ticker_mapping_precision_90: FAIL
- award_and_obligated_amount_precision_95: FAIL
- ceiling_vs_funded_distinction_precision_95: FAIL
- option_modification_precision_90: FAIL
- no_idiq_ceiling_mistaken_for_funded: FAIL

## By Fact


## Non-OK Rows

- government_contract_UNMAPPED_W900KK21F0034 / government_contract_event_type: gold_not_reviewed expected=task_order_award actual=
- government_contract_UNMAPPED_W900KK21F0034 / mapped_ticker: gold_not_reviewed expected=nan actual=
- government_contract_UNMAPPED_W900KK21F0034 / recipient_mapping_confidence: gold_not_reviewed expected=0.0 actual=
- government_contract_UNMAPPED_W900KK21F0034 / award_amount: gold_not_reviewed expected=1890154.84 actual=
- government_contract_UNMAPPED_W900KK21F0034 / obligated_amount: gold_not_reviewed expected=1890154.84 actual=
- government_contract_UNMAPPED_W900KK21F0034 / actual_funded_award_flag: gold_not_reviewed expected=True actual=
- government_contract_UNMAPPED_W900KK21F0034 / ceiling_only_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_W900KK21F0034 / option_exercise_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_W900KK21F0034 / modification_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_H9240821F0007 / government_contract_event_type: gold_not_reviewed expected=task_order_award actual=
- government_contract_UNMAPPED_H9240821F0007 / mapped_ticker: gold_not_reviewed expected=nan actual=
- government_contract_UNMAPPED_H9240821F0007 / recipient_mapping_confidence: gold_not_reviewed expected=0.0 actual=
- government_contract_UNMAPPED_H9240821F0007 / award_amount: gold_not_reviewed expected=13943566.27 actual=
- government_contract_UNMAPPED_H9240821F0007 / obligated_amount: gold_not_reviewed expected=13943566.27 actual=
- government_contract_UNMAPPED_H9240821F0007 / actual_funded_award_flag: gold_not_reviewed expected=True actual=
- government_contract_UNMAPPED_H9240821F0007 / ceiling_only_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_H9240821F0007 / option_exercise_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_H9240821F0007 / modification_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_N6833521F0171 / government_contract_event_type: gold_not_reviewed expected=task_order_award actual=
- government_contract_UNMAPPED_N6833521F0171 / mapped_ticker: gold_not_reviewed expected=nan actual=
- government_contract_UNMAPPED_N6833521F0171 / recipient_mapping_confidence: gold_not_reviewed expected=0.0 actual=
- government_contract_UNMAPPED_N6833521F0171 / award_amount: gold_not_reviewed expected=3094998.0 actual=
- government_contract_UNMAPPED_N6833521F0171 / obligated_amount: gold_not_reviewed expected=3094998.0 actual=
- government_contract_UNMAPPED_N6833521F0171 / actual_funded_award_flag: gold_not_reviewed expected=True actual=
- government_contract_UNMAPPED_N6833521F0171 / ceiling_only_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_N6833521F0171 / option_exercise_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_N6833521F0171 / modification_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_N5523621F9990 / government_contract_event_type: gold_not_reviewed expected=task_order_award actual=
- government_contract_UNMAPPED_N5523621F9990 / mapped_ticker: gold_not_reviewed expected=nan actual=
- government_contract_UNMAPPED_N5523621F9990 / recipient_mapping_confidence: gold_not_reviewed expected=0.0 actual=
- government_contract_UNMAPPED_N5523621F9990 / award_amount: gold_not_reviewed expected=7868792.0 actual=
- government_contract_UNMAPPED_N5523621F9990 / obligated_amount: gold_not_reviewed expected=7868792.0 actual=
- government_contract_UNMAPPED_N5523621F9990 / actual_funded_award_flag: gold_not_reviewed expected=True actual=
- government_contract_UNMAPPED_N5523621F9990 / ceiling_only_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_N5523621F9990 / option_exercise_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_N5523621F9990 / modification_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_N6833521F0198 / government_contract_event_type: gold_not_reviewed expected=task_order_award actual=
- government_contract_UNMAPPED_N6833521F0198 / mapped_ticker: gold_not_reviewed expected=nan actual=
- government_contract_UNMAPPED_N6833521F0198 / recipient_mapping_confidence: gold_not_reviewed expected=0.0 actual=
- government_contract_UNMAPPED_N6833521F0198 / award_amount: gold_not_reviewed expected=17070905.23 actual=
- government_contract_UNMAPPED_N6833521F0198 / obligated_amount: gold_not_reviewed expected=17070905.23 actual=
- government_contract_UNMAPPED_N6833521F0198 / actual_funded_award_flag: gold_not_reviewed expected=True actual=
- government_contract_UNMAPPED_N6833521F0198 / ceiling_only_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_N6833521F0198 / option_exercise_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_N6833521F0198 / modification_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_W900KK21F0051 / government_contract_event_type: gold_not_reviewed expected=task_order_award actual=
- government_contract_UNMAPPED_W900KK21F0051 / mapped_ticker: gold_not_reviewed expected=nan actual=
- government_contract_UNMAPPED_W900KK21F0051 / recipient_mapping_confidence: gold_not_reviewed expected=0.0 actual=
- government_contract_UNMAPPED_W900KK21F0051 / award_amount: gold_not_reviewed expected=1925823.8 actual=
- government_contract_UNMAPPED_W900KK21F0051 / obligated_amount: gold_not_reviewed expected=1925823.8 actual=
- government_contract_UNMAPPED_W900KK21F0051 / actual_funded_award_flag: gold_not_reviewed expected=True actual=
- government_contract_UNMAPPED_W900KK21F0051 / ceiling_only_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_W900KK21F0051 / option_exercise_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_W900KK21F0051 / modification_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_N5005421F5074 / government_contract_event_type: gold_not_reviewed expected=task_order_award actual=
- government_contract_UNMAPPED_N5005421F5074 / mapped_ticker: gold_not_reviewed expected=nan actual=
- government_contract_UNMAPPED_N5005421F5074 / recipient_mapping_confidence: gold_not_reviewed expected=0.0 actual=
- government_contract_UNMAPPED_N5005421F5074 / award_amount: gold_not_reviewed expected=4707753.95 actual=
- government_contract_UNMAPPED_N5005421F5074 / obligated_amount: gold_not_reviewed expected=4707753.95 actual=
- government_contract_UNMAPPED_N5005421F5074 / actual_funded_award_flag: gold_not_reviewed expected=True actual=
- government_contract_UNMAPPED_N5005421F5074 / ceiling_only_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_N5005421F5074 / option_exercise_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_N5005421F5074 / modification_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_N0001921F0149 / government_contract_event_type: gold_not_reviewed expected=task_order_award actual=
- government_contract_UNMAPPED_N0001921F0149 / mapped_ticker: gold_not_reviewed expected=nan actual=
- government_contract_UNMAPPED_N0001921F0149 / recipient_mapping_confidence: gold_not_reviewed expected=0.0 actual=
- government_contract_UNMAPPED_N0001921F0149 / award_amount: gold_not_reviewed expected=2814123.15 actual=
- government_contract_UNMAPPED_N0001921F0149 / obligated_amount: gold_not_reviewed expected=2814123.15 actual=
- government_contract_UNMAPPED_N0001921F0149 / actual_funded_award_flag: gold_not_reviewed expected=True actual=
- government_contract_UNMAPPED_N0001921F0149 / ceiling_only_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_N0001921F0149 / option_exercise_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_N0001921F0149 / modification_flag: gold_not_reviewed expected=False actual=
- government_contract_UNMAPPED_N0001921F0368 / government_contract_event_type: gold_not_reviewed expected=task_order_award actual=
- government_contract_UNMAPPED_N0001921F0368 / mapped_ticker: gold_not_reviewed expected=nan actual=
- government_contract_UNMAPPED_N0001921F0368 / recipient_mapping_confidence: gold_not_reviewed expected=0.0 actual=
