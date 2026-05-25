# Market Reaction Engine

Market Reaction Engine is a generic evidence-backed event intelligence engine: source documents become reviewed, evidence-linked claims, event datasets, quality reports, static sites, APIs, and digests.

The project is intentionally conservative. It is built around auditability, source provenance, compatibility scoring, review status, and explicit quality reporting. It does not treat extracted text as truth just because a parser found it.

## What This Is

MRE turns source material into proof-carrying event data:

```text
SourceAdapter
-> NormalizedSourceDocument
-> CompatibilityReport
-> Entity/Temporal hints
-> EventCandidate
-> ClaimExtractor
-> EvidenceSpan
-> ClaimReviewQueue
-> QualityReport
-> Publisher / API / Digest
```

The current center of gravity is `src/mre/generic`: a source-neutral framework for evidence-backed event intelligence. Source-specific logic lives in plugins and experiments outside the generic core.

## What This Is Not

- Not a stock predictor.
- Not a generic filing, press-release, or news summarizer.
- Not a legal, compliance, investment, or professional truth oracle.
- Not restricted to SEC, U.S., public-company, or official sources.
- Not a system where weak sources are silently discarded or promoted. Weak sources can be routed to lower-readiness use cases with explicit risks.

Event-study, modeling, and backtest modules still exist, but they are downstream research tools, not the main product identity.

## Core Promise

Every claim should carry a receipt:

- source document ID and source URL when available
- evidence text
- character offsets into the normalized source text
- source authority and source role
- extraction confidence
- review status
- claim kind and truth-status language
- quality and compatibility context

The system should make it easy to say:

```text
This field came from this document, this exact text span, under this source role,
with this confidence, this review status, and these known risks.
```

## Compatibility And Confidence

The generic core does not hardcode identifier types such as ticker, CIK, LEI, accession, form, filing item, or source system. Entity identity uses arbitrary namespaces, for example:

```text
company_name
domain
registry:alpha
text:alias
vendor:id
```

Compatibility is scored by dimensions rather than enforced as a binary pass/fail gate. Common dimensions include:

- source authority confidence
- document text quality
- evidence addressability
- metadata completeness
- entity hint quality
- temporal resolution confidence
- event detection confidence
- claim schema alignment
- claim extraction confidence
- reviewability
- provenance completeness

Readiness levels are also scored:

```text
exploration
internal_research
claim_review
user_facing_draft
reviewed_dataset
high_trust_report
```

This lets the same engine handle official records, company releases, specialist research, vendor feeds, news, allegations, or weak early signals without pretending they have the same trust profile.

## Implemented Plugins And Experiments

### Generic Toy Pipeline

The generic toy pipeline proves the source-neutral contracts end to end with an official-like toy source and a weak toy source. It is useful for testing the engine without source-specific assumptions.

### Cyber 8-K Watch

Cyber 8-K Watch is the first real plugin path. It processes Cyber 8-K source-document manifests through the generic plugin runner and produces claims, evidence spans, review queues, quality reports, static sites, API JSON, digests, and provenance.

Cyber 8-K Watch is a pilot workflow, not a claim of complete market coverage or reviewed public data. Parser outputs require review before user-facing high-trust use.

### Official-Company Press-Release Experiment

The official-company press-release experiment is the first non-SEC source-generalization test. It uses local/offline company press-release manifests and exercises the same generic review, quality, publishing, API, digest, and provenance path.

It is an architecture and workflow experiment. Real press-release extraction quality still needs measurement on reviewed real documents.

### Event-Study And Backtest Modules

The original event-study, modeling, walk-forward, falsification, and domain registry work remains available as downstream impact-analysis infrastructure. It is no longer the top-level project framing.

## Quickstart

Install locally:

```bash
python -m venv .venv
python -m pip install -e .[dev]
```

On POSIX shells, activate with:

```bash
source .venv/bin/activate
```

On PowerShell, activate with:

```powershell
.\.venv\Scripts\Activate.ps1
```

Run tests:

```bash
python -m pytest -q
```

Run lint:

```bash
python -m ruff check .
```

Build the package:

```bash
python -m build
```

## Workflow Examples

### Generic Toy Pipeline

Create and run a generic evidence pipeline config:

```bash
mre generic-template \
  --out generic_pipeline.json \
  --out-dir artifacts/generic_toy \
  --adapter toy_official

mre generic-run --config generic_pipeline.json
```

The toy pipeline writes generic documents, event candidates, claims, evidence spans, a review queue, a quality report, API JSON, a static site, a digest, and a run manifest.

### Cyber 8-K Watch Offline Demo

Create a Cyber 8-K config from the included demo source-document manifest:

```bash
mre cyber-8k-template \
  --out cyber_8k_pipeline.json \
  --source-documents-csv examples/cyber_8k_watch/source_documents.csv \
  --out-dir artifacts/cyber_8k_watch

mre cyber-8k-run --config cyber_8k_pipeline.json
```

For real SEC collection, use `cyber-8k-source-docs` with a user agent, then run the Cyber pipeline from the generated manifest:

```bash
mre cyber-8k-source-docs \
  --tickers MSFT VFC UNH \
  --start 2023-12-01 \
  --end 2026-05-25 \
  --out data/cyber_8k/source_documents.csv \
  --docs-dir data/cyber_8k/source_docs \
  --user-agent "Your Name your.email@example.com"

mre cyber-8k-template \
  --out cyber_8k_pipeline.json \
  --source-documents-csv data/cyber_8k/source_documents.csv \
  --out-dir artifacts/cyber_8k_pilot

mre cyber-8k-run --config cyber_8k_pipeline.json
```

### Official-Company Press Releases

Create a local manifest template:

```bash
mre press-release-template --out data/press_releases/source_documents.csv
```

Fill it with manually collected official company press releases, using either `path` or `text` for document content. Then run:

```bash
mre press-release-run \
  --documents data/press_releases/source_documents.csv \
  --out-dir artifacts/press_release_pilot
```

This is offline by design. It does not crawl company websites.

## Review And Quality

Review status is first-class. Common statuses:

```text
human_reviewed
machine_high_confidence
rejected
needs_review
```

`machine_high_confidence` is not the same as human review. User-facing high-trust outputs should distinguish them clearly.

Quality reports track:

- evidence coverage
- review coverage
- human review coverage
- reviewed useful claim yield
- field precision by `field_name`
- rejected and needs-review rates
- review time when available
- issue flags
- parser failure reasons
- source authority, source role, and source system breakdowns
- compatibility dimensions and readiness scores

Review queues are meant to capture both correctness and parser improvement signals. Useful optional review columns include:

```text
review_time_seconds
parser_failure_reason
issue_flags
review_action
reviewer_notes
```

## Common Artifacts

Pipeline outputs vary by plugin, but common artifacts include:

```text
*_documents.csv
*_events.csv
*_claims.csv
*_evidence_spans.csv
*_claim_review_queue.csv
*_quality_report.json
*_quality_report.md
site/
api/
*_digest.md
run_manifest.json
pipeline_report.json
```

The important files are:

- `claims.csv`: structured extracted fields with confidence, source role, claim kind, and evidence IDs.
- `evidence_spans.csv`: evidence text and source offsets.
- `claim_review_queue.csv`: review status, label quality, issue flags, and reviewer notes.
- `quality_report.md/json`: trust, coverage, review, precision, and compatibility metrics.
- `site/`: static HTML inspection surface.
- `api/`: JSON export for downstream consumers.
- `digest.md`: compact Markdown summary.
- `run_manifest.json`: reproducibility metadata and input hashes.
- `pipeline_report.json`: stage outputs, diagnostics, warnings, and compatibility summaries.

Generated runs belong under ignored output directories such as `artifacts/`, `runs/`, or plugin-specific data directories. Small deterministic fixtures belong under `tests/fixtures/` or `examples/`.

## CLI Overview

Evidence-engine commands:

```text
generic-template
generic-run
generic-review-queue
generic-quality-report
generic-build-site
generic-api-export
generic-digest
```

Cyber 8-K Watch commands:

```text
cyber-8k-template
cyber-8k-source-docs
cyber-8k-parse
cyber-8k-review-queue
cyber-8k-build-dataset
cyber-8k-build-site
cyber-8k-digest
cyber-8k-quality-report
cyber-8k-run
```

Official-company press-release experiment commands:

```text
press-release-template
press-release-run
```

Legacy/downstream research commands include event-study, modeling, backtest, corpus, expectations, SEC source-document, and domain-registry commands. Use `mre --help` for the full list.

## Development Guardrails

- Keep `src/mre/generic` source-neutral.
- Do not add Cyber, SEC, ticker, CIK, LEI, accession, filing-form, or other source-specific assumptions to the generic core.
- Put source-specific logic in plugin modules.
- Every new source or domain should produce compatibility reports and quality reports.
- Do not present rejected or unreviewed claims as accepted facts.
- Do not collapse `human_reviewed` and `machine_high_confidence`.
- Do not create user-facing high-trust outputs without review and trust filtering.
- Prefer local fixtures and fake clients in tests. Avoid network-dependent tests.
- Preserve generated artifact hygiene. Do not commit large generated runs.

The generic no-source-assumptions tests enforce the most important boundary: the generic layer must remain clean enough to support sources beyond Cyber 8-K and SEC filings.

## Docs Map

- `docs/DISCLOSURE_INTELLIGENCE_PIVOT.md`: product and architecture pivot toward proof-carrying event intelligence.
- `docs/CYBER_8K_WATCH.md`: Cyber 8-K Watch MVP and target users.
- `docs/OFFICIAL_COMPANY_PRESS_RELEASE_EXPERIMENT.md`: local official-company press-release experiment.
- `docs/RUN_PROVENANCE.md`: reproducibility manifests and run hashes.
- `docs/ARCHITECTURE_MAP.md`: contributor-facing module map.
- `docs/BACKTEST_INTERPRETATION.md`: how to interpret legacy/downstream backtest outputs.
- `docs/DOMAIN_LIFECYCLE.md`: historical domain lifecycle and promotion concepts.
- `docs/DOMAIN_RESEARCH_REGISTRY.md`: historical research-domain status, stop reasons, and revisit triggers.

## Legacy Research Modules

The original market-reaction workbench remains in the repo:

- event-study abnormal return measurement
- price and expectation enrichment
- chronological direction models
- walk-forward evaluation
- calibration tables
- strategy simulation with costs and slippage
- null shuffle tests
- placebo and peer controls
- domain registry and falsification reports

These modules are useful for downstream impact analysis after event data is source-backed and reviewed. They should not be read as evidence that the project has a live tradable signal or graduated trading candidate.

Current posture:

```text
No live tradable candidate.
No graduated tradable signal.
Primary focus: evidence-backed event intelligence and reviewed datasets.
```
