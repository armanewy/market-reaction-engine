# Source-document extraction milestone

Version 0.5 adds the first provenance layer for turning raw documents into reviewable point-in-time facts.

The goal is not to let an LLM predict stock moves. The goal is to make a disciplined conversion layer:

```text
raw source document
→ explicit fact rows with evidence spans
→ expectation-feature rows
→ event rows
→ event-study / model pipeline
```

## What is implemented

### Source-document manifests

Create an empty manifest:

```bash
mre source-docs-template --out data/events/source_documents.csv
```

Each row needs at least:

```text
source_doc_id,ticker,event_time
```

The row can provide either:

```text
text
```

or:

```text
path
```

Relative paths are resolved relative to the manifest file.

### Deterministic extraction baseline

Run extraction:

```bash
mre extract-facts \
  --documents data/events/source_documents.csv \
  --facts-out data/events/extracted_facts.csv \
  --expectations-out data/events/extracted_expectations.csv \
  --events-out data/events/extracted_events.csv
```

Supported fact names:

```text
actual_eps
consensus_eps
consensus_forward_eps
guidance_eps_low
guidance_eps_high
guidance_eps_mid
actual_revenue
consensus_revenue
consensus_forward_revenue
guidance_revenue_low
guidance_revenue_high
guidance_revenue_mid
actual_gross_margin
consensus_gross_margin
consensus_forward_gross_margin
guidance_gross_margin_low
guidance_gross_margin_high
guidance_gross_margin_mid
```

Every fact row includes:

```text
source_doc_id
event_id
ticker
event_time
fact_name
value
unit
confidence
method
evidence_text
start_char
end_char
source_type
source_url
```

### LLM packet generation without API calls

Create JSONL work packets for an external model:

```bash
mre extraction-packets \
  --documents data/events/source_documents.csv \
  --out data/events/extraction_packets.jsonl
```

The packet includes allowed fact names and instructions to extract only explicitly supported facts.

### Validated LLM fact ingestion

Validate external LLM results:

```bash
mre validate-llm-facts \
  --documents data/events/source_documents.csv \
  --llm-jsonl data/events/llm_facts.jsonl \
  --out data/events/validated_llm_facts.csv
```

By default, the validator requires each `evidence_text` to appear in the corresponding source document.

Expected JSONL shape:

```json
{"source_doc_id":"doc1","event_id":"evt1","facts":[{"fact_name":"actual_revenue","value":2450.0,"unit":"usd_millions","evidence_text":"ACME reported revenue of $2.45 billion.","confidence":0.9}]}
```

## Offline demo

```bash
mre extraction-demo --root .
```

Outputs:

```text
data/extraction_demo/source_documents.csv
data/extraction_demo/docs/*.txt
data/extraction_demo/extracted_facts.csv
data/extraction_demo/extracted_expectations.csv
data/extraction_demo/extracted_events.csv
data/extraction_demo/extraction_diagnostics.json
```

## Limitations

The deterministic extractor is intentionally conservative and incomplete. It is useful as a transparent baseline and test harness, not as a production parser. Real use should include manual review, stronger document normalization, section-aware parsing, and/or validated LLM outputs.

The important discipline is that extracted facts must be based only on source text available at or before `event_time`; they must never be labeled using the subsequent price reaction.
