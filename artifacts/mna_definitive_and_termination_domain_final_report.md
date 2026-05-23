# M&A Definitive Agreements And Terminations Final Report

Verdict: continue corpus buildout.

Stop point: no parsed event rows. No modeling is permitted until readiness and execution survivability pass.

## Domain

- Domain name: mna_definitive_and_termination
- Research question: Do definitive M&A announcements and deal terminations produce abnormal returns after controlling for role, premium, payment method, deal size, and termination reason?
- Primary sources: SEC 8-K Items 1.01, 1.02, 2.01; merger exhibits; Exhibit 99 press releases; S-4/proxy only when needed.
- Benchmarks: SPY primary; sector ETF only when available.

## Lifecycle Status

- scaffold/source discovery/parser: implemented for manifest-driven SEC/press-release documents
- review queue: machine candidates are unreviewed; hard negatives are rejected
- parser audit: required before modeling
- context enrichment: target/acquirer market cap, deal-value scale, premium, run-up, and liquidity scaffolding implemented
- timestamp and duplicate audit: implemented; exact public sessions required
- readiness gates: evaluated below
- first falsification/fresh confirmation/final signal verdict: not reached

## Execution Survivability Gate

- gate_pass: False
- reason: no event rows
- class_counts: {}
- plausibly_tradeable_after_first_entry_rows: 0

Classification policy:

- Target deal announcements/tender offers: immediate-gap. They may explain close-to-close abnormal returns, but usually are not tradable after the first realistic next-open entry unless merger-spread or competing-bid setup evidence exists.
- Terminations, regulatory blocks, financing failures, shareholder-vote failures, and revised terms: delayed-digestion or slow-burn repricing. They may remain tradable because standalone value, break fees, financing, litigation, and regulatory path can be reassessed after the first print.
- Completion events: explanation-only unless there is an independently auditable residual spread or unexpected close timing.
- Any modeled pass must report both close-to-close and next-open behavior with 25/50/100 bps execution stress. A close-to-close explanatory effect is not a tradable result if next-open fails.

## Readiness Gates

- parser_audit_pass: FAIL
- reviewed_usable_events_100_min: FAIL
- target_announcement_events_40: FAIL
- termination_or_break_events_30: FAIL
- role_coverage_80: FAIL
- deal_terms_context_rows_50: FAIL
- clear_public_timestamps_80: FAIL
- primary_duplicate_rows_95pct: FAIL
- likely_oos_predictions_30: FAIL
- execution_survivability_gate: FAIL

## Summary Counts

- parsed_event_rows: 0

## Blocking Items

- parser_audit_pass
- reviewed_usable_events_100_min
- target_announcement_events_40
- termination_or_break_events_30
- role_coverage_80
- deal_terms_context_rows_50
- clear_public_timestamps_80
- primary_duplicate_rows_95pct
- likely_oos_predictions_30
- execution_survivability_gate

## Hard Negatives

- Ordinary commercial agreements, licensing/collaboration deals, non-binding LOIs/MOUs, amendments with no economic change, immaterial asset acquisitions, private targets without public-equity reaction, and duplicate press-release/8-K/proxy rows are excluded from model eligibility.

## Pre-Registered Hypotheses

1. Definitive acquisition announcement is positive for target.
2. Deal termination is negative for target.
3. Acquirer reaction depends on deal size and payment method.
4. Regulatory block/financing failure termination is more negative than mutual termination.
5. Completion event itself is weaker if expected.

## Artifacts

- source manifest: not built in this pass
- parser errors: not available
