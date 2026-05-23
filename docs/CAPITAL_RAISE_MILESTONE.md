# Capital Raises / Dilution Milestone

This milestone starts the capital-raises domain as a data-product track, not a prediction track.

The research question is:

```text
Do equity offerings, ATM programs, convertibles, shelf registrations, and liquidity warnings produce measurable abnormal returns after controlling for market context, offering size, discount, pre-event run-up, and dilution risk?
```

The first implementation only creates source-grounded candidate rows:

```text
source document
-> parsed financing facts
-> reviewable feature rows
-> review-queue event rows
```

It intentionally does not run a model.

## Domain

The corpus domain is:

```text
capital_raise_dilution
```

Supported event labels include:

```text
completed_equity_offering
announced_equity_offering
registered_direct_offering
private_placement
atm_program_created
atm_program_usage_reported
convertible_note_offering
shelf_registration
prospectus_supplement
going_concern_warning
liquidity_warning
```

The important distinction is transaction versus capacity:

```text
completed_financing_flag
immediate_dilution_flag
capacity_only_flag
```

Shelf registrations and new ATM programs are capacity signals until reviewed evidence shows an actual sale.

## Parser Command

Build SEC source-document candidates:

```bash
mre capital-raise-sec-source-docs \
  --tickers MRNA PLUG RIVN \
  --start 2020-01-01 \
  --end 2026-05-23 \
  --docs-dir data/source_docs/capital_raises \
  --out data/events/capital_raise_source_documents.csv
```

The default SEC source pass targets:

```text
8-K items: 1.01, 2.03, 3.02, 8.01
registration/prospectus forms: S-1, S-3, 424B2, 424B3, 424B4, 424B5, 424B7
```

The 8-K items are used to find current reports for material agreements, direct financial obligations, unregistered equity sales, and other financing events. Registration statements and prospectus supplements are included separately because they usually do not have 8-K item strings.

```bash
mre parse-capital-raises \
  --documents data/events/capital_raise_source_documents.csv \
  --facts-out data/events/capital_raise_facts.csv \
  --features-out data/events/capital_raise_features.csv \
  --events-out data/events/capital_raise_review_queue.csv
```

Important extracted fields:

```text
financing_event_type
security_type
offering_amount
gross_proceeds
net_proceeds
shares_offered
price_per_share
atm_capacity
convertible_principal
conversion_price
use_of_proceeds
underwriter_or_agent
going_concern_warning
liquidity_warning
financing_amount_best
financing_amount_source
financing_amount_confidence
immediate_dilution_flag
capacity_only_flag
completed_financing_flag
```

## Parser Audit Command

Validate against a reviewed gold set before modeling:

```bash
mre validate-capital-raise-parser \
  --facts data/events/capital_raise_facts.csv \
  --gold data/events/capital_raise_parser_gold_set.csv \
  --errors-out data/events/capital_raise_parser_errors.csv \
  --report-out data/events/capital_raise_parser_audit_report.md
```

Gold rows should include:

```text
event_id
fact_name
expected_value
unit
tolerance
```

Suggested audit gates:

```text
event_type precision >= 95%
offering_amount/gross_proceeds precision >= 95%
price_per_share precision >= 90%
shares_offered precision >= 90%
convertible_principal precision >= 90%
ATM capacity precision >= 90%
no shelf-capacity mistaken for immediate offering amount
no ATM capacity mistaken for completed sale
```

## Context Enrichment Command

After review, add economic severity context:

```bash
mre capital-raise-shares-context \
  --events data/events/capital_raise_reviewed_corpus.csv \
  --out data/events/capital_raise_shares_outstanding.csv

mre enrich-capital-raise-context \
  --events data/events/capital_raise_reviewed_corpus.csv \
  --prices-dir data/prices/capital_raises \
  --benchmark SPY \
  --shares-outstanding data/events/capital_raise_shares_outstanding.csv \
  --market-caps data/events/capital_raise_market_caps.csv \
  --out data/events/capital_raise_enriched.csv
```

This computes:

```text
last_close_before_event
discount_to_last_close_pct
market_cap_before_event
financing_amount_pct_market_cap
shares_outstanding_before_event
shares_outstanding_source
shares_outstanding_asof_date
shares_outstanding_filed_at
estimated_dilution_pct
atm_capacity_pct_market_cap
convertible_principal_pct_market_cap
pre_event_market_adjusted_return_20d
pre_event_market_adjusted_return_60d
```

The share-count join uses the latest SEC `EntityCommonStockSharesOutstanding`
fact with `filed_at <= event_time`. Current market-cap snapshots are not valid
for historical events.

## Readiness Report

Before modeling, write a data-readiness report:

```bash
mre capital-raise-readiness-report \
  --events data/events/capital_raise_enriched.csv \
  --out data/events/capital_raise_readiness_report.md
```

The report checks:

```text
candidate rows
reviewed usable rows
completed financing rows
capacity-only rows
rows with financing_amount_pct_market_cap
rows with discount_to_last_close_pct
likely OOS predictions at min_train=40
top missing gates blocking modeling
```

## Modeling Gate

Do not model this domain until there is a reviewed corpus with:

```text
100+ reviewed usable events preferred, 80+ minimum
60+ completed financing events
40+ rows with financing_amount_pct_market_cap
40+ rows with discount_to_last_close_pct where applicable
clear event timestamps
offering amount or ATM/convertible principal coverage
price/discount coverage where applicable
market-cap or shares-outstanding context
placebo and peer controls
walk-forward validation
cost/slippage simulation
```

The parser output is a review queue, not a model-ready corpus.
