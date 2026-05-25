# Official-Company Press Release Experiment

This experiment tests whether the generic evidence engine can handle a non-SEC source shape without changing the generic core. It is an offline workflow for manually collected official company press releases, not a crawler and not a new public product vertical.

The source profile is intentionally different from Cyber 8-K filings:

```text
source_authority_level = official_company
source_role = canonical or context
entity_hints = company_name and domain
temporal_hints = published_at with lower confidence than regulatory acceptance time
claim schema = press_release_cyber_claims
```

The goal is to compare extraction quality, review yield, source-role behavior, and compatibility/readiness scores against the Cyber 8-K path and the generic toy sources.

## Manifest

Create a manifest template:

```bash
mre press-release-template --out data/press_releases/source_documents.csv
```

Columns:

```text
source_record_id
source_url
title
published_at
retrieved_at
document_type
document_subtype
source_authority_level
source_role
jurisdiction
company_name
domain
path
text
```

Use either `path` or `text` for document content. `path` is resolved relative to the manifest location. Prefer `path` for real pilot work so source text remains inspectable as a separate artifact.

## Run

Run the offline experiment:

```bash
mre press-release-run \
  --documents data/press_releases/source_documents.csv \
  --out-dir artifacts/press_release_pilot
```

Outputs include:

```text
press_release_documents.csv
press_release_events.csv
press_release_claims.csv
press_release_evidence_spans.csv
press_release_claim_review_queue.csv
press_release_quality_report.json
press_release_quality_report.md
api/
site/
press_release_digest.md
run_manifest.json
pipeline_report.json
```

## Review

Use the same review taxonomy as Cyber 8-K Watch:

```text
human_reviewed
machine_high_confidence
rejected
needs_review
```

Track `issue_flags`, `parser_failure_reason`, and `review_time_seconds` when reviewing a real pilot. The key metric is reviewed useful claim yield, not claim volume.

## Scope

This is source-generalization work. Do not add live network fetching or new source-specific logic to `src/mre/generic`. If this experiment performs well on real press releases, the next step is a measured pilot with field-level precision and review-time reporting.
