# Cyber 8-K Watch

Cyber 8-K Watch is the first Disclosure Intelligence Engine vertical. It tracks SEC cybersecurity incident disclosures and produces evidence-backed event and claim datasets.

## MVP

The MVP is a small, inspectable product:

- latest Item 1.05 and 8-K/A cybersecurity disclosures
- company pages with disclosure timelines
- event detail pages with structured fields and evidence spans
- JSON/CSV export for downstream workflows
- weekly digest of notable disclosures and amendments

## Target Users

- disclosure counsel
- securities litigators
- cyber incident response firms
- cyber insurers and risk teams
- investor relations and communications advisors
- journalists and researchers

## MVP Fields

Each field should be backed by source evidence or explicitly marked as missing / unreviewed:

- `item_105_flag`
- `amendment_flag`
- `ransomware_mentioned`
- `customer_data_exposure_mentioned`
- `operational_disruption_mentioned`
- `third_party_vendor_mentioned`
- `financial_impact_language`
- `materiality_language`
- `impact_unknown_or_not_determined`
- `no_material_impact_language`
- `reasonably_likely_material_impact_language`

Additional useful fields:

- `cybersecurity_incident_event_type`
- `incident_discovery_date`
- `materiality_determination_date`

## MVP Pages

- latest filings
- company page
- event detail page
- API/export JSON

## Validation Criteria

Pass/fail market validation should be based on real workflow pull, not compliments:

- 20 user conversations
- 5 requests for alerts, export, or API access
- 2 serious paid-pilot asks

If users only find the product intellectually interesting but do not ask for data, alerts, exports, or API access, the MVP has not validated.

For the launch checklist, interview script, task tests, pricing hypotheses, and kill criteria, see `docs/CYBER_8K_WATCH_LAUNCH_PLAN.md`.
