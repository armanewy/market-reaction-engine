# Government Contract Parser Audit Report

This validates parser facts against a reviewed gold set. It is a parser-quality report, not a model result.

## Metrics

- gold_rows: 0
- gold_events: 0
- correct_rows: 0
- status: no_gold_rows
- parser_audit_pass: False

## Audit Gates

- gold_set_60_rows: FAIL
- event_type_precision_95: FAIL
- recipient_ticker_mapping_precision_90: FAIL
- award_and_obligated_amount_precision_95: FAIL
- ceiling_vs_funded_distinction_precision_95: FAIL
- option_modification_precision_90: FAIL
- no_idiq_ceiling_mistaken_for_funded: FAIL

## By Fact

