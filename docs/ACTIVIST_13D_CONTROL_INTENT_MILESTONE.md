# Activist 13D Control-Intent Domain

This milestone adds a non-modeling scaffold for `activist_13d_control_intent`.

## Scope

- Source discovery: SEC EDGAR `SC 13D`, `SC 13D/A`, `SC 13G`, and `SC 13G/A` source-document candidates.
- Parser: Schedule 13D/13G form inference, Item 4 extraction, beneficial owner, ownership percentage, shares owned, ownership-change direction, source-of-funds category, agreements/exhibits hints, activist/control/board/sale/passive flags, and hard-negative taxonomy.
- Review queue: facts pivot to feature rows and event rows with machine-candidate review status.
- Audits: parser gold-set validation, timestamp and duplicate audit.
- Context: market cap, pre-event market-adjusted 20d/60d run-up, prior 13D activity, and liquidity placeholders.
- Readiness: source/review/parser/timestamp/duplicate/context gates block modeling until they pass.
- Execution survivability: events are pre-classified as immediate-gap, delayed-digestion, slow-burn repricing, pre-event setup, or explanation-only before any modeling.

## Commands

```powershell
python -m mre.cli activist-13d-source-docs --tickers XYZ --out data/events/activist_13d_sources.csv --docs-dir data/source_docs/activist_13d
python -m mre.cli parse-activist-13d --documents data/events/activist_13d_sources.csv --facts-out artifacts/activist_13d_facts.csv --features-out artifacts/activist_13d_features.csv --events-out artifacts/activist_13d_events.csv
python -m mre.cli validate-activist-13d-parser --facts artifacts/activist_13d_facts.csv --gold data/events/activist_13d_gold.csv --errors-out artifacts/activist_13d_parser_errors.csv --report-out artifacts/activist_13d_parser_audit.md
python -m mre.cli activist-13d-timestamp-audit --events artifacts/activist_13d_events.csv --out artifacts/activist_13d_timestamp_audit.csv
python -m mre.cli enrich-activist-13d-context --events artifacts/activist_13d_timestamp_audit.csv --prices-dir data/prices --market-caps data/events/market_caps.csv --out artifacts/activist_13d_context.csv
python -m mre.cli activist-13d-readiness-report --events artifacts/activist_13d_context.csv --source-documents data/events/activist_13d_sources.csv --parser-errors artifacts/activist_13d_parser_errors.csv --out artifacts/activist_13d_control_intent_domain_final_report.md
```

Do not run event studies, falsification, or modeling until the readiness report says `model-ready`.
