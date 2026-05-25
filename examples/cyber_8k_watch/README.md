# Cyber 8-K Watch Demo

This is a tiny offline demo for the proof-carrying Cyber 8-K Watch workflow. The documents are synthetic and intentionally small.

Run the parser:

```bash
mre cyber-8k-parse --documents examples/cyber_8k_watch/source_documents.csv --claims-out artifacts/cyber_8k_watch/claims.csv --evidence-out artifacts/cyber_8k_watch/evidence.csv
```

Build the dataset and static site:

```bash
mre cyber-8k-build-dataset --documents examples/cyber_8k_watch/source_documents.csv --out-dir artifacts/cyber_8k_watch
mre cyber-8k-build-site --events artifacts/cyber_8k_watch/cyber_events.csv --claims artifacts/cyber_8k_watch/cyber_claims.csv --evidence-spans artifacts/cyber_8k_watch/cyber_evidence_spans.csv --out-dir artifacts/cyber_8k_watch/site
```

Every extracted field should point back to an evidence span in the synthetic source text.
