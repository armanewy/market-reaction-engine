# M7 — Real source ingestion

Version 0.6 adds a source-ingestion layer that downloads or normalizes real source documents into the existing `source_documents.csv` manifest format. The goal is to keep ingestion auditable and separate from extraction:

```text
SEC filing / exhibit / investor-relations URL / transcript URL / local HTML or text
→ normalized text file
→ source-document manifest
→ evidence-grounded extraction
→ expectation/event rows
→ event study
```

## New commands

### Create a seed manifest

```bash
mre ingestion-template --out data/events/source_ingestion_template.csv
```

Rows can provide one of:

- `source_url` for a company press release, transcript page, agency document, etc.
- `path` for a local HTML/text file.
- `text` for a small inline source.

The required metadata for useful extraction is still `ticker` and `event_time`.

### Normalize URL/local/inline documents

```bash
mre ingest-source-docs \
  --input data/events/source_ingestion_template.csv \
  --out data/events/source_documents_ingested.csv \
  --docs-dir data/source_docs/normalized \
  --requests-per-second 2 \
  --overwrite
```

The output manifest is compatible with:

```bash
mre extract-facts \
  --documents data/events/source_documents_ingested.csv \
  --facts-out data/events/extracted_facts.csv \
  --expectations-out data/events/extracted_expectations.csv \
  --events-out data/events/extracted_events.csv
```

### Ingest SEC filing documents and earnings exhibits

```bash
export SEC_USER_AGENT="market-reaction-engine your-email@example.com"

mre sec-source-docs \
  --preset semis \
  --start 2022-01-01 \
  --end 2025-01-01 \
  --item-filter 2.02 \
  --docs-dir data/source_docs/sec \
  --out data/events/sec_source_documents.csv
```

Defaults:

- form filter: `8-K`
- item filter: `2.02`
- includes the primary filing document.
- includes likely earnings-release exhibits matching names like `ex99`, `ex-99`, `dex99`, `99.1`, `earnings`, `results`, or `press release`.

Disable filters as needed:

```bash
mre sec-source-docs \
  --tickers AAPL MSFT \
  --item-filter all \
  --forms 8-K,10-Q,10-K \
  --no-exhibits \
  --docs-dir data/source_docs/sec \
  --out data/events/sec_primary_docs.csv
```

## Offline demo

```bash
mre source-ingestion-demo --root .
```

This writes a local HTML earnings release, normalizes it into a text file, produces a source manifest, and runs extraction.

## Why this matters

The project now has a reproducible chain from raw source material to extracted evidence. This is critical for avoiding silent hallucinated features. Every fact row can trace back to a normalized document and evidence span.

## Limitations

- The HTML normalizer is dependency-free and conservative; it is not a full browser or production HTML parser.
- SEC filing exhibit selection is heuristic. Review downloaded rows before modeling.
- This milestone does not add paid transcript or analyst-estimate feeds. Those can now plug into the same source manifest or expectation manifest path.
- Downloaded and extracted facts should still be reviewed before any trading use.
