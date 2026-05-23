# SEC Core Infrastructure Report

## Scope

This pass adds shared SEC-native source, review, context, timestamp, and readiness infrastructure. It does not run prediction models, event studies, or backtests.

## Commands

- `mre sec-domain-source-docs`: discovers supported SEC filings for a domain/ticker/form/date slice, downloads primary documents, filters 8-K items, and writes a reusable source manifest.
- `mre sec-domain-review-template`: turns a source manifest or parser event file into a human review queue with standardized eligibility fields.
- `mre sec-domain-context`: adds pre-event price, market, liquidity, size, and point-in-time capitalization fields.
- `mre sec-domain-timestamp-audit`: selects SEC-aware event timestamps and first tradable reaction windows while marking ambiguous or invalid rows ineligible.
- `mre sec-domain-readiness-report`: summarizes source, parser, review, timestamp, context, and power gates for SEC-native domains.

## Supported SEC Forms

- `8-K`, `8-K/A`
- `4`, `4/A`
- `SC 13D`, `SC 13D/A`
- `SC 13G`, `SC 13G/A`

## Supported 8-K Items

- `1.01`, `1.02`, `1.03`, `1.05`
- `2.04`, `2.06`
- `3.01`
- `4.01`, `4.02`
- `5.02`
- `8.01`

## Modeling Boundary

The shared commands prepare auditable corpora and eligibility gates only. Rows with ambiguous timestamps, invalid reaction windows, or unverified historical market capitalization are marked `model_eligible=false`.
