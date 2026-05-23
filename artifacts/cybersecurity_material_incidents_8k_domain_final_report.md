# Cybersecurity Material Incidents 8-K Domain Final Report

Domain: `cybersecurity_material_incidents_8k`

## Final Verdict

Status: `parser not trusted / continue corpus buildout`

No model was run. The domain does not yet pass non-modeling readiness gates because there is no reviewed Item 1.05 corpus, no human-reviewed parser audit, no timestamp/duplicate audit over real filings, and no market-cap/run-up/sector-control context coverage. Per project rules, this is a hard stop before first falsification.

## Research Question

Do material cybersecurity incident disclosures produce negative abnormal returns after controlling for company size, incident type, operational disruption, customer-data exposure, and stated financial impact?

## Execution Survivability Gate

Classification: `delayed-digestion`

Rationale: Item 1.05 filings can trigger immediate headline gaps, but the tradable hypothesis is not just the first headline. Disclosure details often remain incomplete at the first realistic entry point: operational recovery, customer-data scope, financial impact, insurance offsets, and no-material-impact amendments may arrive later. That leaves a plausible delayed-digestion or slow-burn repricing window only after strict timestamp, duplicate, public-awareness, and context gates pass.

If this domain later becomes model-eligible, both close-to-close and next-open performance must be reported. Intraday entry should be required for any immediate-gap slice; otherwise the immediate headline component is explanation-only.

## Lifecycle Status

- Scaffold: complete. Added `mre.cybersecurity_incidents` with domain constants, parser, source-builder, context enrichment, timestamp/duplicate audit, parser validation, and readiness report helpers.
- Source discovery: scaffolded. SEC EDGAR source builder targets `8-K` and `8-K/A`, Item `1.05`, from `2023-12-18` forward, with related exhibit matching.
- Parser: initial rule parser complete. It extracts Item 1.05 flag, incident discovery date, materiality determination date, operational disruption, ransomware, customer-data exposure, third-party/vendor flag, financial-impact language, business-interruption language, amendments, no-material-impact language, known-before-filing flags, hard-negative reason, and pre-price direction/materiality labels.
- Review queue/parser audit: blocked until real source documents are collected and reviewed.
- Context enrichment: scaffolded. Supports market cap, sector, revenue, pre-event market-adjusted return, pre-event volatility, company size bucket, data-sensitive sector flag, and prior cyber incident flag.
- Timestamp + duplicate audit: scaffolded. Blocks duplicate source filings and known-public-before-filing rows from eligibility.
- Readiness gates: implemented. Current domain has no reviewed real corpus, so gates fail.
- First falsification: not eligible.
- Fresh confirmation: not eligible.
- Final modeling verdict: no signal graduation; no thresholds tuned; no returns modeled.

## Hard Negatives

The parser and readiness gates explicitly guard against:

- Generic cybersecurity risk/control language.
- Vendor vulnerability or security advisory not tied to the company.
- Non-material incident language.
- No-material-impact amendments.
- Duplicated press release/8-K rows.
- Incidents known publicly before the filing.

## Pre-Registered Hypotheses

1. Material cyber incident with operational disruption is negative.
2. Ransomware/business interruption is more negative than generic breach.
3. Customer-data exposure is negative, especially in consumer/healthcare.
4. No-material-impact amendment is weak/control.
5. Legacy non-Item 1.05 disclosures are noisier than Item 1.05.

## Readiness Gate Snapshot

- `reviewed_usable_events_80_min`: FAIL
- `item_105_events_50`: FAIL
- `material_incident_events_50`: FAIL
- `operational_or_ransomware_events_20`: FAIL
- `market_cap_context_rows_40`: FAIL
- `pre_event_context_rows_40`: FAIL
- `clear_event_timestamps`: FAIL
- `duplicate_timestamp_audit_pass`: FAIL until real audit is run
- `hard_negative_review_pass`: FAIL until reviewed hard negatives exist
- `likely_oos_predictions_30`: FAIL
- `sector_benchmark_controls_ready`: FAIL
- `parser_audit_pass`: FAIL

## Files Added For Domain Work

- `src/mre/cybersecurity_incidents.py`
- `tests/test_cybersecurity_incidents.py`
- `artifacts/cybersecurity_material_incidents_8k_domain_final_report.md`

## Stop Reason

The first hard gate failure is parser/review readiness: there is no human-reviewed parser audit and no reviewed source-backed event corpus. Modeling now would violate the project rule against modeling before readiness passes.
