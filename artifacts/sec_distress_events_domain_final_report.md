# SEC Distress Events Domain Final Report

This is a domain-readiness report, not a prediction result. No return model, threshold tuning, fresh confirmation, or final signal graduation was run.

## Verdict

- domain: `sec_distress_events`
- research question: Do formal SEC distress disclosures produce negative abnormal returns after controlling for market cap, prior drawdown, event subtype, and liquidity?
- lifecycle stop: source discovery / parser-audit readiness
- verdict: not model-ready
- hard gate failure: no reviewed SEC distress corpus and no human-reviewed parser audit exist in this branch
- allowed next step: build a source-backed 8-K corpus from EDGAR Items 3.01, 1.03, 2.04, and 2.06, then review parser candidates, hard negatives, duplicate amendments, timestamp quality, halt/illiquidity status, and next-open execution behavior before any event study

## Implemented Domain Scaffold

- Added `sec_distress_events` corpus schema with SEC item, subtype, deficiency, bankruptcy/default/impairment, hard-negative, duplicate, timestamp, market-cap, drawdown, liquidity, and execution-survivability fields.
- Added a source-document builder wrapper for SEC EDGAR 8-K Items `1.03,2.04,2.06,3.01`.
- Added parser logic for delisting/listing-rule deficiencies, bankruptcy/receivership, debt acceleration/default, material impairment, compliance cure/regain, extension/appeal, and reverse-split-plan controls.
- Added context enrichment for share price, penny-stock flag, dollar volume, market cap ratios, and 20/60-day market-adjusted pre-event returns.
- Added parser validation and readiness gates so modeling is blocked until parser audit, review, timestamp, subtype coverage, market-cap, prior-drawdown, liquidity, and out-of-sample-count gates pass.

## Execution Survivability Gate

Required classification before modeling:

- `immediate-gap`
- `delayed-digestion`
- `slow-burn repricing`
- `pre-event setup`
- `explanation-only`

Current classification: `explanation-only`.

Reason: SEC distress disclosures often involve halted, delisting-bound, sub-$5, or very illiquid issuers. A close-to-close abnormal return may explain public information diffusion, but it is not tradable unless next-open behavior remains negative after realistic entry and cost stress.

If this domain later reaches modeling eligibility, every result must report:

- close-to-close behavior
- next-open behavior
- 25 bps, 50 bps, and 100 bps stress-cost behavior
- explicit statement that close-to-close explanatory effects are not tradable when next-open behavior fails
- why any residual effect should remain tradeable after the first realistic entry

Hard rule: do not treat a close-to-close explanatory effect as tradable if next-open behavior fails.

## Hard Negatives

The parser explicitly separates these from negative distress events:

- compliance regained / deficiency cured
- exchange extension or appeal/hearing granted
- reverse split plan without actual delisting notice
- routine or previously announced impairment language requiring review exclusion
- duplicate amendments

These rows are control/review candidates, not negative-event labels.

## Readiness Gates

Minimum gates before modeling:

- 80 reviewed usable negative distress events, with 100 preferred
- 60 negative distress events after hard negatives are removed
- 20 delisting/listing-rule events
- 10 bankruptcy/receivership events
- 10 debt acceleration/default events
- 40 rows with market-cap context
- 40 rows with prior 20-day market-adjusted drawdown context
- 40 rows with liquidity/dollar-volume context
- clear public timestamps for all reviewed usable rows
- next-open execution audit for all reviewed usable rows
- zero reviewed usable rows marked close-to-close explanatory-only
- at least 30 likely out-of-sample predictions after a 40-row minimum training window
- at least 60 human-reviewed parser-audit rows at 90%+ precision

## Pre-Registered Hypotheses

1. Bankruptcy/receivership disclosures are negative.
2. Debt acceleration/default disclosures are negative.
3. Delisting notices are negative, especially equity-deficiency notices.
4. Compliance cure/regain notices are positive or weak controls.
5. Execution audit is critical because many names may be halted or illiquid.

## Final Decision

Stop here. The branch now has domain machinery to discover, parse, review, audit, enrich, and gate SEC distress events, but it does not yet contain a reviewed and audited corpus or next-open execution survivability evidence. Modeling or falsification would violate the registered lifecycle.
