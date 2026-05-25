# Disclosure Intelligence Pivot

MRE is pivoting from market-reaction research toward proof-carrying corporate event intelligence. The first vertical is Cyber 8-K Watch: a source-backed dataset and report layer for SEC cybersecurity incident disclosures.

The product direction is:

```text
source document
-> filing
-> event
-> claim
-> evidence span
-> review status
-> provenance and timestamp status
-> dataset / API / report
```

The core promise is simple: every structured field has a receipt. A user should be able to inspect a field such as `ransomware_mentioned`, `impact_unknown_or_not_determined`, or `materiality_language` and immediately see the filing, document, exact evidence text, review state, timestamp status, and run provenance behind it.

## Not A Filing Summarizer

This is not a generic filing search or summarization tool. Generic summarizers produce useful prose but often make it difficult to audit exactly why a structured field was created. The Disclosure Intelligence Engine should produce records that are reviewable, exportable, and defensible:

- claims are tied to source documents
- evidence spans are explicit
- timestamps and release sessions are classified
- review status is first-class
- generated artifacts can carry run provenance
- uncertainty and missing evidence are visible

## Current MRE Foundations

The existing research infrastructure maps well to this pivot:

- `source_docs` and `ingestion`: normalize source documents into auditable manifests.
- extraction evidence spans: establish the source-backed field discipline.
- review queues: separate machine extraction from accepted data.
- `domain_schema`: gives domains explicit field and gate definitions.
- promotion gates: keep draft data from being treated as model-ready.
- `timestamp_readiness`: distinguishes explanatory records from execution-ready timestamps.
- `provenance`: records code, config, and input hashes.
- event study and backtest: remain available as optional downstream impact analysis, not the primary product.

## First Vertical

Cyber 8-K Watch should focus on SEC Item 1.05 cybersecurity disclosures and amendments. The first usable product should answer practical disclosure-intelligence questions:

- Which companies filed new cybersecurity incident disclosures?
- Which filings mention operational disruption, ransomware, vendors, customer data, or unknown impact?
- Which disclosures were later amended?
- How does this disclosure compare with similar prior disclosures?
- What exact evidence supports each structured field?

## Out Of Scope

These should stay out of scope until Cyber 8-K Watch works end to end:

- stock prediction as the primary product
- general filing search
- broad multi-domain expansion
- chat-first UX
- unsupported claims without evidence receipts

The research engine remains valuable, but the product center of gravity is now source-backed corporate event data.
