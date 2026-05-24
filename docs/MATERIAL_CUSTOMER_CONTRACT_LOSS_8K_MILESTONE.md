# Material Customer / Contract Loss 8-K Milestone

Status: parser not trusted / continue corpus buildout

This local run tested the Domain Finder candidate `material_customer_contract_loss_8k` using official SEC EDGAR source documents. No model, event study, falsification pass, fresh confirmation, or execution audit was run because readiness gates did not pass.

## Thesis

Public-company disclosures of material customer or contract loss may require delayed market digestion because investors need to infer lost revenue, customer concentration, guidance impact, margin impact, replacement probability, and liquidity or covenant consequences.

## Source Discovery

Source path: SEC EDGAR full-text search and SEC submissions metadata.

The run queried official SEC 8-K / 8-K/A filings from 2018-01-01 through 2026-05-24 for material customer, largest customer, customer concentration, termination, non-renewal, reduced order, and contract termination phrases.

Outputs:

- `data/events/material_customer_contract_loss_8k/source_documents.csv`
- `data/events/material_customer_contract_loss_8k/source_query_stats.json`
- `data/events/material_customer_contract_loss_8k/docs/`

Counts:

- SEC source rows: 191
- unique mapped tickers: 166
- downloaded primary documents: 191

## Parser Result

The parser was intentionally strict after an initial loose pass generated obvious false positives from merger, employment, financing, lease, and generic transaction termination language.

Strict parser output:

- parsed rows: 191
- ambiguous customer/contract mention rows: 187
- customer concentration context-only rows: 1
- new-customer/customer-win hard negatives: 2
- machine-proposed material customer-loss rows: 1
- machine-proposed model-eligible rows: 1

Manual spot audit found the only machine-proposed material customer-loss row was a false positive: a Stryker Item 1.05 / 7.01 cybersecurity and operations impact disclosure where customer impact was mentioned only as a possible effect.

## Gate Result

Readiness decision: continue corpus buildout

SEC-CORE readiness counts:

- source rows: 191
- parsed rows: 191
- reviewed usable rows: 0
- model eligible rows: 1
- likely OOS predictions with `min_train=40`: 0

Gate status:

- parser audit status: fail
- timestamp audit status: pass
- timestamp rows OK: 155 / 191
- context coverage: 0.0

Top missing gates:

- reviewed usable rows
- parser audit status
- context coverage
- likely OOS predictions

## Verdict

Do not model this corpus.

The current broad SEC 8-K search and rule parser are not sufficient for a material customer / contract loss research domain. The main blocker is not timestamp quality; it is source precision and parser trust. The run did not find enough credible current lost-customer disclosures to create a reviewed corpus or a 60-row parser gold set.

## Revisit Trigger

Revisit only with a better source strategy or narrower thesis, for example:

- issuer filings explicitly using loss/non-renewal/reduced-orders language in the same local evidence window as a named material customer
- 10-Q / 10-K customer concentration context linked to a current 8-K loss event
- hand-seeded known customer-loss disclosures to bootstrap a true parser gold set
- source queries that exclude merger, employment, financing, lease, and generic transaction termination contexts

Do not launch a falsification/modeling run from this artifact set.
