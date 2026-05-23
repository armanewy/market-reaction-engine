# Activist 13D Control-Intent Domain Final Report

Date: 2026-05-23

## Verdict

- domain: `activist_13d_control_intent`
- verdict: `continue corpus buildout`
- hard gate reached: `source_documents_recovered_100`
- modeling status: not attempted
- falsification status: not eligible
- fresh confirmation status: not eligible

The domain now has source-discovery, parser, review-queue, parser-audit, timestamp/duplicate-audit, context-enrichment, readiness-gate, and execution-survivability scaffolding. No live reviewed corpus was available in this branch, and no issuer ticker universe was supplied for a real 2015-present SEC pull. The process therefore stops at the first hard gate failure: no reviewed source corpus exists yet.

## Lifecycle Status

- scaffold: complete
- source discovery: scaffolded through SEC EDGAR `SC 13D`, `SC 13D/A`, `SC 13G`, and `SC 13G/A` source-document candidates
- parser: complete for first-pass rule extraction of Schedule 13D/13G form, Item 4 purpose text, reporting owner, ownership percentage, shares owned, ownership-change direction, source of funds, agreements/exhibits hints, activist/control/board/sale/passive flags, and hard negatives
- review queue: complete through facts -> features -> events conversion
- parser audit: scaffolded; requires a reviewed gold set before trust gate can pass
- context enrichment: scaffolded for market cap, pre-event 20d/60d market-adjusted run-up, prior 13D activity, and liquidity/float placeholders
- timestamp and duplicate audit: complete scaffold; must pass before modeling
- readiness gates: complete
- first falsification: blocked
- fresh confirmation: blocked
- final verdict: continue corpus buildout

## Current Readiness Gates

- source_documents_recovered_100: FAIL
- reviewed_usable_events_80_min: FAIL
- initial_active_or_control_events_50: FAIL
- hard_negative_controls_30: FAIL
- ownership_pct_rows_60: FAIL
- market_cap_context_rows_40: FAIL
- pre_event_runup_rows_40: FAIL
- clear_timestamps_80: FAIL
- duplicate_audit_pass: FAIL
- likely_oos_predictions_30: FAIL
- parser_audit_pass: FAIL

Stop condition: source and reviewed-corpus gates fail before parser trust, context, event-study, or modeling gates can be evaluated.

## Execution Survivability Gate

- required status before modeling: every candidate slice must be classified before returns are inspected
- allowed classes: immediate-gap, delayed-digestion, slow-burn repricing, pre-event setup, explanation-only
- current status: NOT EVALUATED FOR MODELING because readiness gates fail before modeling
- first realistic entry policy: after-close SEC acceptances use next open; before-open acceptances use same-day open or next open; intraday acceptances use first liquid trade after acceptance
- tradeability rule: close-to-close effects are explanatory only unless next-open behavior survives implementation stress
- required modeling outputs if eligible later: close-to-close behavior, next-open behavior, and 25/50/100 bps stress results
- required rejection rule: do not treat a close-to-close explanatory effect as tradable if next-open behavior fails

Domain prior:

- board-seat, control-intent, strategic-alternatives, and sale-pressure 13D filings are delayed-digestion candidates because investors may need time to price activist credibility, settlement odds, board vulnerability, ownership scale, and potential transaction paths
- generic initial activist 13D filings and ownership-increase amendments are slow-burn repricing candidates when Item 4 language supports active engagement but not an immediate board/sale campaign
- passive or ambiguous 13D rows and 13G filings are explanation-only controls unless next-open behavior independently survives stress
- ownership-decrease and exit amendments are immediate-gap or negative-control candidates; they should not be assumed tradeable after first realistic entry without next-open evidence

## Hard Negatives Preserved

- `SC 13G` passive filings are controls, not activist positives
- 13D/A ownership decreases and exits are hard negatives
- amendments with no new intent or tiny ownership changes are not positive campaigns
- passive institutional ownership and legal-entity restructuring language should be rejected during review
- founder/insider filings without activist language stay passive or ambiguous

## Pre-Registered Hypotheses

1. Initial 13D with activist/control language is positive.
2. Board/strategic-alternatives/sale language is stronger than generic investment language.
3. Ownership decreases and exit amendments are negative or weak.
4. Passive 13G filings are weaker controls.

## Implementation Added

- `src/mre/activist_13d.py`
- `tests/test_activist_13d.py`
- `docs/ACTIVIST_13D_CONTROL_INTENT_MILESTONE.md`
- `src/mre/corpus.py` domain schema and aliases
- `src/mre/cli.py` CLI commands for the domain lifecycle

## Verification

- `.\.venv\Scripts\python.exe -m pytest tests\test_activist_13d.py -q`: 11 passed
- `.\.venv\Scripts\python.exe -m pytest tests\test_corpus_milestone.py -q`: 2 passed
- `.\.venv\Scripts\python.exe -m mre.cli --help`: passed
- `.\.venv\Scripts\python.exe -m pytest -q`: 164 passed
