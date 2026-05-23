# Government Contract Awards Milestone

This milestone starts the government-contract-awards domain as a data-product track, not a prediction track.

The research question is:

```text
Do government contract awards, task orders, option exercises, SBIR/STTR awards, OTA/prototype awards, and large IDIQ/contract vehicle announcements produce measurable abnormal returns after controlling for award size, funded amount vs ceiling, market cap, revenue scale, contract type, pre-event run-up, and whether the event is an actual funded award or only capacity?
```

The first implementation creates source-grounded candidate rows:

```text
official/source document
-> parsed government-contract facts
-> reviewable feature rows
-> review-queue event rows
-> audit/readiness reports
```

It intentionally does not run a model, event study, backtest, or prediction.

## Domain

The corpus domain is:

```text
government_contract_awards
```

Supported event labels include:

```text
new_contract_award
task_order_award
contract_modification
option_exercise
idiq_vehicle_award
contract_ceiling_only
sbir_award
sttr_award
ota_prototype_award
production_contract
recompete_win
contract_extension
subcontract_award
ambiguous_contract_event
```

The important distinction is funded value versus capacity:

```text
actual_funded_award_flag
ceiling_only_flag
modification_flag
option_exercise_flag
new_work_flag
incumbent_or_extension_flag
prime_contractor_flag
subcontractor_flag
recipient_mapping_confidence
materiality_context_required_flag
```

A $1B IDIQ ceiling is not treated as a $1B funded award. A task order is not treated as a contract vehicle. A modification may be incremental, administrative, or an option exercise and must be reviewed before use.

## Recipient Mapping

Create or update the recipient-to-ticker mapping:

```bash
mre government-contract-source-docs \
  --mapping data/events/government_contract_recipient_ticker_map.csv \
  --out data/events/government_contract_source_documents.csv
```

Suggested mapping columns:

```text
recipient_name_pattern
ticker
public_company_name
subsidiary_name
mapping_type
confidence
source_url
notes
```

Rows with ambiguous or low-confidence mappings are preserved for review but are not emitted with a model-eligible ticker. Subsidiary and JV mappings require evidence; ambiguous JV rows such as United Launch Alliance must not be mapped to a parent ticker without event-specific support.

Mapping types accepted as model-eligible are deliberately narrow:

```text
exact_public_company
known_subsidiary
division
```

Rows with `ambiguous`, `private_company`, `reject`, `joint_venture`, low confidence, blank ticker, or multi-ticker mappings remain review-only until a human adds evidence.

Audit mapping coverage with:

```bash
mre government-contract-mapping-audit \
  --source-documents data/events/government_contract_source_documents.csv \
  --mapping data/events/government_contract_recipient_ticker_map.csv \
  --report-out data/events/government_contract_mapping_audit_report.md \
  --detail-out data/events/government_contract_mapping_audit.csv
```

## Source Discovery

USAspending source rows can be pulled with:

```bash
mre government-contract-source-docs \
  --use-usaspending \
  --tickers PLTR KTOS AVAV RKLB LUNR RDW BKSY PL \
  --start 2024-01-01 \
  --end 2026-05-23 \
  --limit-per-recipient 3 \
  --pages-per-recipient 1 \
  --mapping data/events/government_contract_recipient_ticker_map.csv \
  --out data/events/government_contract_source_documents.csv
```

Manifest-driven DoD, company press release, SEC, or manually collected source documents can be merged:

```bash
mre government-contract-source-docs \
  --manifest data/events/manual_government_contract_sources.csv \
  --mapping data/events/government_contract_recipient_ticker_map.csv \
  --out data/events/government_contract_source_documents.csv
```

The output is still a source-document candidate manifest, not a reviewed corpus.

## Parser Command

Parse source documents into facts, features, and a review queue:

```bash
mre parse-government-contracts \
  --documents data/events/government_contract_source_documents.csv \
  --facts-out data/events/government_contract_facts.csv \
  --features-out data/events/government_contract_features.csv \
  --events-out data/events/government_contract_review_queue.csv
```

Important extracted facts:

```text
recipient_name
mapped_ticker
parent_company_name
agency
sub_agency
award_amount
obligated_amount
contract_ceiling
award_type
contract_type
contract_number
task_order_number
modification_number
period_of_performance_start
period_of_performance_end
product_or_service_description
naics_code
psc_code
location
prime_or_sub
new_vs_modification
option_exercise_flag
recompete_or_extension_flag
source_evidence_text
confidence
parser_quality_flags
```

Review queue fields include:

```text
event_id
ticker
event_time
release_session
source_type
source_url
government_contract_event_type
actual_funded_award_flag
ceiling_only_flag
new_work_flag
modification_flag
option_exercise_flag
recipient_mapping_confidence
award_amount
obligated_amount
contract_ceiling
agency
product_or_service_description
materiality_pre_price
review_status
evidence_status
label_quality
drop_reason
review_notes
```

## Parser Audit

Create a machine-proposed 60-event gold-set template with:

```bash
mre government-contract-gold-template \
  --features data/events/government_contract_features.csv \
  --out data/events/government_contract_parser_gold_set.csv \
  --target-events 60
```

The template is not a passing audit. Rows are marked `gold_review_status=needs_human_review`, and `validate-government-contract-parser` will fail with `gold_set_requires_human_review` until a reviewer confirms expected values.

Validate against a reviewed gold set:

```bash
mre validate-government-contract-parser \
  --facts data/events/government_contract_facts.csv \
  --gold data/events/government_contract_parser_gold_set.csv \
  --errors-out data/events/government_contract_parser_errors.csv \
  --report-out data/events/government_contract_parser_audit_report.md
```

The 60-event gold set should include:

```text
15 new funded contract awards
10 task orders
10 contract modifications / options
10 IDIQ or ceiling-only contract vehicles
5 SBIR/STTR/OTA awards
5 company press-release contract announcements
5 ambiguous/subsidiary-mapping cases
```

Audit gates:

```text
event_type precision >= 95%
recipient/ticker mapping precision >= 90%
award_amount / obligated_amount precision >= 95%
ceiling vs funded amount distinction precision >= 95%
option/modification classification precision >= 90%
no IDIQ ceiling mistaken for fully funded award
no subsidiary/JV recipient mapped to parent ticker unless evidence supports it
no old/repeated contract announcement treated as new event
```

## Context Enrichment

After review, add economic/materiality context:

```bash
mre enrich-government-contract-context \
  --events data/events/government_contract_reviewed_corpus.csv \
  --prices-dir data/prices/government_contracts \
  --benchmark SPY \
  --market-caps data/events/government_contract_market_caps.csv \
  --revenue data/events/government_contract_revenue_ltm.csv \
  --out data/events/government_contract_enriched.csv
```

This computes:

```text
last_close_before_event
market_cap_before_event
revenue_ltm_if_available
award_amount_pct_market_cap
obligated_amount_pct_market_cap
contract_ceiling_pct_market_cap
award_amount_pct_revenue
pre_event_market_adjusted_return_20d
pre_event_market_adjusted_return_60d
sector_benchmark
company_size_bucket
small_cap_flag
```

Current market-cap snapshots are not valid for historical events. Use event-time or point-in-time market cap/revenue context.

## Readiness Report

Write the non-modeling readiness report:

```bash
mre government-contract-readiness-report \
  --events data/events/government_contract_enriched.csv \
  --source-documents data/events/government_contract_source_documents.csv \
  --parser-errors data/events/government_contract_parser_errors.csv \
  --out data/events/government_contract_readiness_report.md
```

The report includes:

```text
source documents recovered
parsed event rows
reviewed usable rows
actual funded award rows
ceiling-only rows
modification/option rows
rows with recipient mapping confidence high
rows with award_amount_pct_market_cap
rows with obligated_amount_pct_market_cap
rows with contract_ceiling_pct_market_cap
rows with pre-event market-adjusted run-up
likely OOS predictions with min_train=40
top missing fields blocking modeling
ticker concentration
```

## Modeling Gate

Do not model this domain until:

```text
100+ reviewed usable events preferred, 80 minimum
60+ actual funded award events
40+ rows with award_amount_pct_market_cap or obligated_amount_pct_market_cap
30+ rows from small/mid-cap names, not only large primes
recipient mapping audit passes
parser audit passes
clear event timestamps
likely OOS predictions >= 30
placebo/peer controls can be built
```

## Pre-Registered Hypotheses

Hypothesis 1:

```text
small/mid-cap company
AND actual_funded_award_flag = true
AND obligated_amount_pct_market_cap >= 5%
Expected: positive abnormal return.
```

Hypothesis 2:

```text
contract_ceiling_only_flag = true
Expected: weaker/noisier reaction than actual funded awards.
```

Hypothesis 3:

```text
new_work_flag = true
AND award_amount_pct_market_cap >= 5%
Expected: stronger positive reaction than modification/option-extension awards.
```

Hypothesis 4:

```text
large prime contractor
AND award_amount_pct_market_cap < 1%
Expected: no meaningful abnormal return.
```

Hypothesis 5:

```text
positive pre-event run-up before award announcement
Expected: weaker reaction or possible sell-the-news if the award was anticipated.
```

## Initial Verdict

Initial domain verdict should be one of:

```text
model-ready
continue corpus buildout
parser not trusted
mapping insufficient
context insufficient
domain not promising
```

At this milestone, the expected verdict is not model-ready until the source corpus, mapping audit, parser audit, review status, timestamp quality, and market-cap context gates pass.

## Agent 4B Run

Agent 4B executed a broad USAspending corpus and mapping/context stress test. No prediction model, event study, or backtest was run.

Commands run:

```bash
mre parse-government-contracts \
  --documents data/events/government_contract_source_documents.csv \
  --facts-out data/events/government_contract_facts.csv \
  --features-out data/events/government_contract_features.csv \
  --events-out data/events/government_contract_review_queue.csv

mre government-contract-mapping-audit \
  --source-documents data/events/government_contract_source_documents.csv \
  --mapping data/events/government_contract_recipient_ticker_map.csv \
  --report-out data/events/government_contract_mapping_audit_report.md \
  --detail-out data/events/government_contract_mapping_audit.csv

mre government-contract-gold-template \
  --features data/events/government_contract_features.csv \
  --out data/events/government_contract_parser_gold_set.csv \
  --target-events 60

mre validate-government-contract-parser \
  --facts data/events/government_contract_facts.csv \
  --gold data/events/government_contract_parser_gold_set.csv \
  --errors-out data/events/government_contract_parser_errors.csv \
  --report-out data/events/government_contract_parser_audit_report.md

mre enrich-government-contract-context \
  --events data/events/government_contract_review_queue.csv \
  --prices-dir data/prices/government_contracts \
  --benchmark SPY \
  --market-caps data/events/government_contract_market_caps.csv \
  --out data/events/government_contract_enriched.csv

mre government-contract-readiness-report \
  --events data/events/government_contract_enriched.csv \
  --source-documents data/events/government_contract_source_documents.csv \
  --parser-errors data/events/government_contract_parser_errors.csv \
  --out data/events/government_contract_readiness_report.md
```

4B output summary:

```text
source_documents_recovered: 1562
parsed_event_rows: 1554
reviewed_usable_rows: 0
actual_funded_award_rows: 1545
ceiling_only_rows: 9
modification_or_option_rows: 30
rows_with_recipient_mapping_confidence_high: 1388
rows_with_award_amount_pct_market_cap: 1216
rows_with_obligated_amount_pct_market_cap: 1208
rows_with_contract_ceiling_pct_market_cap: 10
rows_with_pre_event_market_adjusted_runup: 1385
small_mid_cap_rows: 404
likely_oos_predictions_min_train: 0
parser_audit_rows: 540
parser_audit_accuracy: 0.0
```

Mapping audit summary:

```text
source_rows: 1562
unique_recipients: 84
model_eligible_recipients: 70
model_eligible_source_rows: 1396
mapping_type_counts:
  exact_public_company: 67
  known_subsidiary: 3
  unmapped: 14
```

The 4B verdict is:

```text
parser not trusted
```

Main blockers:

```text
reviewed_usable_events_80_min
reviewed_usable_events_100_preferred
clear_event_timestamps
likely_oos_predictions_30
parser_audit_pass
```

The corpus now has enough candidate volume and materiality context for a review pass, but not enough reviewed data. The next milestone is human review of the gold set, recipient/ticker edge cases, and timestamp supplementation from DoD daily announcements, SEC filings, and company press releases.
