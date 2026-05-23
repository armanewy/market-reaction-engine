# Accounting Integrity 8-K Domain Final Report

## Verdict

- domain: `accounting_integrity_8k`
- verdict: `STOP - source discovery insufficient`
- first hard gate failure: source discovery / recovered corpus
- modeling status: not attempted
- falsification status: not eligible
- fresh confirmation status: not eligible

This pass adds the domain scaffold, parser, parser-audit hooks, context enrichment, timestamp/duplicate audit, readiness gates, and execution survivability gate. It does not graduate the signal. The repository does not yet contain a reviewed SEC Item 4.01/4.02 corpus large enough to pass the first source-discovery gate, so the lifecycle stops before modeling.

## Domain Definition

`accounting_integrity_8k` covers U.S.-listed SEC filers with 8-K Item 4.01 or 4.02 events from 2015-present:

- Item 4.02 non-reliance on previously issued financial statements.
- Restatement warnings and accounting error corrections.
- Auditor resignation, dismissal, disagreements, reportable events, and Exhibit 16 auditor letters.
- Internal-control language only when tied to a substantive accounting-integrity event.

Hard negatives are explicitly handled as non-severe candidates: routine auditor rotation, auditor dismissal with no disagreement, amended filings without non-reliance, internal-control boilerplate only, restatements already disclosed earlier, and audit-firm changes due merger/acquisition.

## Lifecycle Status

1. Scaffold: complete.
   - Added domain module: `src/mre/accounting_integrity_8k.py`.
   - Registered corpus schema and aliases in `src/mre/corpus.py`.
   - Added tests in `tests/test_accounting_integrity_8k.py`.

2. Source discovery: blocked.
   - Implemented SEC submissions source-discovery helper for recent 8-K / 8-K/A Item 4.01 and 4.02 rows.
   - The repository does not yet include a broad 2015-present source manifest for this domain.
   - Gate: `source_documents_recovered_100 = FAIL`.

3. Parser: scaffolded and unit-tested.
   - Extracts `item_number`, `non_reliance_flag`, `affected_periods`, `restatement_reason`, `auditor_change_type`, `prior_auditor`, `new_auditor`, disagreement/reportable-event flags, auditor-letter presence/agreement, hard-negative status, severity, evidence, and confidence.
   - Parser distinguishes "no disagreements" routine changes from actual auditor disagreements.

4. Review queue: scaffolded.
   - Parsed events are emitted as `review_status = unreviewed`.
   - Human review is required before readiness can pass.

5. Parser audit: scaffolded.
   - Gold template and validation functions are present.
   - Unreviewed gold templates are rejected.
   - Gate remains failed until a reviewed gold set reaches minimum coverage and accuracy.

6. Context enrichment: scaffolded.
   - Supports market cap before event, 20-day pre-event market-adjusted return, 20-day volatility, Big 4 auditor flag, company size bucket, prior 12-month accounting events, and prior late-filing flag placeholder.

7. Timestamp and duplicate audit: scaffolded.
   - Audits clear public timestamp sessions and duplicate event keys.
   - Modeling requires primary events only and clear timestamps.

8. Readiness gates: blocked.
   - Readiness requires source coverage, reviewed usable events, high-severity coverage, Item 4.02 coverage, auditor resignation/disagreement/reportable-event coverage, market context, parser audit, timestamp/duplicate audit, execution survivability, and enough out-of-sample rows.
   - Current status fails before modeling because source discovery has not produced the required corpus.

9. First falsification: not eligible.
10. Fresh confirmation: not eligible.
11. Final signal verdict: not graduated.

## Execution Survivability Gate

- domain-level class: `delayed-digestion`
- first realistic entry: next open after SEC acceptance timestamp
- tradeability rule: close-to-close effects are explanatory only unless next-open behavior survives costs
- required stress if modeled: close-to-close and next-open behavior with 25 bps, 50 bps, and 100 bps execution stress

Rationale: many severe accounting-integrity 8-Ks arrive after close or before open and can gap immediately, but the information is often text-heavy and heterogeneous: affected periods, auditor letters, disagreement language, reportable events, internal-control scope, and restatement severity are not always instantly summarized by headline feeds. That creates a plausible delayed-digestion channel after the first realistic entry, but only for high-severity cases such as Item 4.02 non-reliance, auditor resignation, auditor disagreement, reportable events, or auditor-letter disagreement.

This domain must not treat a negative close-to-close result as tradable if the next-open result fails after 25/50/100 bps stress. Routine auditor changes remain `explanation-only` or low-severity controls, not short signals.

## Pre-Registered Hypotheses

1. Item 4.02 non-reliance events are negative.
2. Auditor resignation, disagreement, and reportable events are more negative than routine auditor changes.
3. Small/mid-cap accounting-integrity events are more severe than large-cap routine changes.
4. Auditor-letter disagreement is more severe than auditor-letter agreement.

## Required Next Work

- Build a 2015-present SEC Item 4.01/4.02 source manifest for U.S.-listed filers, prioritizing small/mid-cap companies and all Item 4.02 rows.
- Fetch primary 8-K documents and Exhibit 16 letters where present.
- Create a reviewed gold set before trusting parser output.
- Run timestamp and duplicate audits before any return study.
- Add market cap, prior 20-day market-adjusted return, volatility, auditor Big 4 status, company size bucket, and prior accounting-event context.
- Only after readiness passes, run first falsification with both close-to-close and next-open execution-stress reporting.
