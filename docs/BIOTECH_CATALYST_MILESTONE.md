# Biotech FDA / Clinical Catalyst Milestone

This milestone starts the `biotech_fda_clinical_catalyst` domain as a data-product track, not a prediction track.

The research question is:

```text
Do FDA decisions, clinical-trial readouts, advisory committee votes, trial halts, safety signals, and label-expansion events produce measurable abnormal returns after controlling for market context, company size, pipeline concentration, event type, trial phase, and pre-event run-up?
```

The first implementation only creates source-grounded candidate rows:

```text
source document / official event
-> parsed source-grounded facts
-> reviewable feature rows
-> review-queue event rows
-> parser audit / readiness report
```

It intentionally does not run an event study, prediction model, or backtest.

## Domain

The corpus domain is:

```text
biotech_fda_clinical_catalyst
```

Supported event labels include:

```text
fda_approval
fda_complete_response_letter
fda_advisory_committee_positive
fda_advisory_committee_negative
phase_1_readout
phase_2_readout
phase_3_readout
pivotal_trial_readout
trial_halt
trial_discontinuation
safety_signal
endpoint_failure
endpoint_success
label_expansion
accelerated_approval
priority_review
breakthrough_designation
fast_track_designation
orphan_drug_designation
```

Designation-only events are deliberately separated from approvals and Phase 2/3 outcomes:

```text
binary_catalyst_flag
clinical_trial_readout_flag
regulatory_decision_flag
designation_only_flag
safety_negative_flag
approval_or_label_expansion_flag
trial_failure_flag
trial_success_flag
pipeline_concentration_required_flag
```

Fast Track, Breakthrough Therapy, Orphan Drug, and Priority Review can be directionally positive, but they are weaker signals and are not treated as approvals.

## Source Discovery

Build SEC and manifest-driven source-document candidates:

```bash
mre biotech-catalyst-source-docs \
  --tickers MRNA BMRN SAGE \
  --start 2020-01-01 \
  --end 2026-05-23 \
  --docs-dir data/source_docs/biotech_catalysts \
  --out data/events/biotech_catalyst_source_documents.csv
```

The first automated pass targets SEC 8-K Items `7.01` and `8.01` plus likely press-release exhibits. This is intentionally conservative because exact 8-K timestamps are auditable.

Company press releases, FDA pages, FDA press releases, advisory committee materials, openFDA rows, and ClinicalTrials.gov/NCT-linked rows should be added through source-document manifests:

```bash
mre biotech-catalyst-source-docs \
  --no-sec \
  --source-manifests data/events/manual_biotech_sources.csv \
  --docs-dir data/source_docs/biotech_catalysts \
  --out data/events/biotech_catalyst_source_documents.csv
```

Manual source manifests use the standard `source_documents.csv` schema:

```text
source_doc_id,ticker,event_id,event_time,event_type,event_subtype,release_session,source_type,source_url,title,path,text,fiscal_period_end,sector_benchmark,notes
```

Rows may provide `path` to normalized local text or inline `text`. If a row only has a URL, first run `mre ingest-source-docs` to download and normalize it into a parser-ready source-document manifest. Use `source_type` values such as `company_press_release`, `sec_exhibit`, `fda`, `fda_advisory_material`, `clinicaltrials`, or `openfda`.

openFDA and ClinicalTrials.gov are useful for supporting metadata, but first-pass labels should prefer company releases, SEC 8-Ks, FDA pages/releases, advisory committee materials, and approval/CRL-related source documents.

## Parser Command

```bash
mre parse-biotech-catalysts \
  --documents data/events/biotech_catalyst_source_documents.csv \
  --facts-out data/events/biotech_catalyst_facts.csv \
  --features-out data/events/biotech_catalyst_features.csv \
  --events-out data/events/biotech_catalyst_review_queue.csv
```

Important extracted fields:

```text
drug_asset
indication
event_type
trial_phase
nct_id
trial_name
primary_endpoint
endpoint_met
p_value
hazard_ratio
response_rate
overall_survival
progression_free_survival
safety_issue
adverse_event_language
fda_action
approval_status
complete_response_letter_flag
advisory_committee_vote_for
advisory_committee_vote_against
pdufa_date
accelerated_approval_flag
label_expansion_flag
affected_pipeline_asset_count
company_pipeline_concentration_notes
source_evidence_text
confidence
parser_quality_flags
```

Label rules:

```text
event_direction_pre_price is based only on source facts, not price movement.
Allowed directions: positive, negative, mixed, neutral, unknown.
Phase 3 primary endpoint success can be positive.
Phase 3 endpoint failure, CRL, trial halt, and major safety signal can be negative.
"Encouraging data" without endpoint clarity should be mixed or unknown.
Enrollment updates, conference presentations, and publication notices are not binary catalysts unless they contain new efficacy/safety data.
```

## Parser Audit

Validate against a human-reviewed gold set:

```bash
mre validate-biotech-catalyst-parser \
  --facts data/events/biotech_catalyst_facts.csv \
  --gold data/events/biotech_catalyst_parser_gold_set.csv \
  --errors-out data/events/biotech_catalyst_parser_errors.csv \
  --report-out data/events/biotech_catalyst_parser_audit_report.md
```

To bootstrap review, create a parser-proposed 60-row template:

```bash
mre validate-biotech-catalyst-parser \
  --facts data/events/biotech_catalyst_facts.csv \
  --gold data/events/biotech_catalyst_parser_gold_set.csv \
  --errors-out data/events/biotech_catalyst_parser_errors.csv \
  --report-out data/events/biotech_catalyst_parser_audit_report.md \
  --build-gold-template
```

The template is not a trusted audit until a human reviewer confirms or corrects the expected values.

Audit gates:

```text
event_type precision >= 95%
drug_asset / indication precision >= 90%
trial_phase precision >= 90%
endpoint_success/failure precision >= 90%
regulatory decision precision >= 95%
no designation-only event mistaken for approval
no enrollment/update event mistaken for readout
no publication/conference notice mistaken for new topline result
```

## Context Enrichment

Context fields can be merged into the reviewed queue before readiness evaluation:

```text
market_cap_before_event
pre_event_market_adjusted_return_20d
pre_event_market_adjusted_return_60d
pipeline_concentration_proxy
single_asset_company_flag
cash_runway_proxy
sector_benchmark, preferably XBI or IBB
peer basket fields if feasible
```

These are point-in-time controls, not model outputs.

## Readiness Report

```bash
mre biotech-catalyst-readiness-report \
  --events data/events/biotech_catalyst_review_queue.csv \
  --source-documents data/events/biotech_catalyst_source_documents.csv \
  --parser-errors data/events/biotech_catalyst_parser_errors.csv \
  --out data/events/biotech_catalyst_readiness_report.md
```

The report includes:

```text
source documents recovered
parsed event rows
reviewed usable rows
binary catalyst rows
FDA/regulatory decision rows
Phase 2/3 readout rows
negative catalyst rows
positive catalyst rows
rows with market cap context
rows with pre-event run-up context
rows with source evidence
parser audit precision
likely OOS predictions with min_train=40
top missing fields blocking modeling
```

## Modeling Gate

Do not model until:

```text
100+ reviewed usable events preferred, 80 minimum
60+ binary catalyst events
30+ negative catalyst events
30+ positive catalyst events
40+ rows with market_cap_before_event
40+ rows with pre_event_market_adjusted_return_20d
parser audit passes
event timestamps are clear
likely OOS predictions >= 30
placebo/peer controls can be built
```

Pre-registered candidate hypotheses:

```text
1. Small/mid-cap biotech AND binary negative catalyst -> expected negative abnormal return.
2. Phase 3 or pivotal readout AND endpoint_met=true AND no major safety issue -> expected positive abnormal return, especially for pipeline-concentrated companies.
3. Complete response letter OR trial halt OR endpoint_failure -> expected negative abnormal return.
4. designation_only_flag=true -> expected weaker/noisier reaction than approvals/readouts.
5. Positive catalyst after strong pre-event run-up -> expected weaker reaction or sell-the-news risk.
```

The parser output is a review queue, not a model-ready corpus.
