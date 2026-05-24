# Material Customer / Contract Loss 8-K Final Report

Verdict: parser not trusted / continue corpus buildout.

No model, event study, backtest, fresh confirmation, or final execution audit was run. The domain stopped at parser/readiness gates.

## Canonical Context

- No graduated signal exists.
- No live candidate exists.
- SEC-CORE remains the durable MRE infrastructure.
- Domain Finder approved this as a full-lifecycle candidate with a 25/30 intake score.
- This run tested whether the domain could reach MRE readiness. It did not.

## Source Corpus

Official source: SEC EDGAR 8-K / 8-K/A filings.

Source method:

- SEC EDGAR full-text search over customer and contract-loss phrases.
- SEC submissions API for filing acceptance timestamps.
- SEC archive primary document download for parser evidence.

Counts:

- source rows: 191
- parsed rows: 191
- unique mapped tickers: 166
- downloaded primary documents: 191
- duplicate accession groups: 0

## Parser Findings

Strict parser output:

- material_customer_loss: 1
- customer_concentration_context_only: 1
- new_customer_win: 2
- ambiguous_customer_event: 187

Manual spot audit found the sole machine-proposed `material_customer_loss` row was false. It was an Item 1.05 / 7.01 cybersecurity and operations impact disclosure, not a customer or contract loss event.

The broad search corpus was dominated by non-event contexts:

- merger and business-combination termination language
- employment agreement termination language
- financing and warrant agreement language
- lease and landlord termination provisions
- generic forward-looking risk language
- customer concentration or customer mention without a current loss event

## Readiness

SEC-CORE readiness decision: `continue corpus buildout`.

Counts:

- source rows: 191
- parsed rows: 191
- reviewed usable rows: 0
- model eligible rows: 1
- likely OOS predictions with `min_train=40`: 0

Gate status:

- parser audit status: fail (`18` parser audit rows are not OK)
- timestamp audit status: pass (`155/191` rows OK)
- context coverage: 0.0

Top missing gates:

- reviewed usable rows
- parser audit status
- context coverage
- likely OOS predictions

## Decision

Stop. Do not model.

This domain remains conceptually plausible, but this source-and-parser path is not ready. The run did not produce an auditable corpus of true material customer-loss events, and the parser would create false tradability risk if used downstream.

## Produced Artifacts

- `data/events/material_customer_contract_loss_8k/source_documents.csv`
- `data/events/material_customer_contract_loss_8k/source_query_stats.json`
- `data/events/material_customer_contract_loss_8k/facts.csv`
- `data/events/material_customer_contract_loss_8k/features.csv`
- `data/events/material_customer_contract_loss_8k/review_queue.csv`
- `data/events/material_customer_contract_loss_8k/reviewed_corpus.csv`
- `data/events/material_customer_contract_loss_8k/parser_gold_set.csv`
- `data/events/material_customer_contract_loss_8k/parser_audit.csv`
- `data/events/material_customer_contract_loss_8k/parser_audit_report.md`
- `data/events/material_customer_contract_loss_8k/timestamp_audit.csv`
- `data/events/material_customer_contract_loss_8k/duplicate_audit.csv`
- `data/events/material_customer_contract_loss_8k/enriched.csv`
- `data/events/material_customer_contract_loss_8k/readiness_report.md`
- `data/events/material_customer_contract_loss_8k/run_summary.json`

## Registry Recommendation

Status: `parser not trusted`

Revisit trigger: new source strategy or manually seeded gold set proving enough current material customer-loss disclosures. Do not rerun the same broad 8-K customer/termination query path.
