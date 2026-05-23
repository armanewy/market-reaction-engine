# Exhibit 99 Parser Milestone

This milestone adds a specialized parser for semiconductor Exhibit 99 earnings
releases. It is separate from the generic source-document extractor because the
semiconductor guidance use case needs stricter handling of:

- current-quarter actual revenue
- current-quarter EPS
- current-quarter gross margin
- next-quarter revenue guidance
- plus/minus guidance ranges such as `$2.60 billion +/- $100 million`
- period roles such as `current_quarter_actual` and `next_quarter_guidance`

The parser is intentionally conservative. It emits evidence spans, confidence
scores, parse methods, and quality flags, but parser output must be validated
against a reviewed gold set before use in modeling.

## Commands

Parse a source-document manifest:

```bash
mre parse-exhibit99 \
  --documents data/events/semis_exhibit99_source_documents.csv \
  --facts-out data/events/semis_exhibit99_parsed_facts.csv \
  --features-out data/events/semis_exhibit99_parsed_features.csv
```

Validate against a gold set:

```bash
mre validate-exhibit99-parser \
  --facts data/events/semis_exhibit99_parsed_facts.csv \
  --gold data/events/semis_exhibit99_parser_gold_set.csv \
  --errors-out data/events/semis_exhibit99_parser_errors.csv \
  --report-out data/events/semis_exhibit99_parser_validation_report.md
```

## Modeling Gate

Do not use parsed fields for a management-guidance model until the gold set is
independently reviewed. The preferred gate is:

- actual revenue precision >= 95%
- guidance revenue midpoint precision >= 90%
- no plus/minus range failures
- no current-quarter actuals confused with next-quarter guidance
- no segment revenue confused with consolidated revenue

