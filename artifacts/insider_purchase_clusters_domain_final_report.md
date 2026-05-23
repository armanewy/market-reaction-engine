# Insider Purchase Clusters Domain Final Report

Date: 2026-05-23

## Verdict

Decision: continue corpus buildout. Do not model.

Hard gate failure: no reviewed insider-purchase corpus, no human-reviewed parser gold set, no timestamp/duplicate audit sample, and no execution survivability evidence. The domain is scaffolded through parser, context, audit, and readiness gates, but the evidence does not yet allow falsification or modeling.

## Domain Scope

Research question: Do clustered open-market insider purchases predict positive abnormal returns after controlling for market cap, pre-event run-up/drawdown, insider role, transaction size, and prior purchase history?

Primary sources: SEC EDGAR submissions API, Form 4 XML ownership reports, and SEC companyfacts or supplied context for shares outstanding / market-cap context.

Primary signal definition: transaction code P, acquired shares, positive shares and price, non-derivative transaction, no 10b5-1 / planned-trade language, and a reviewed officer/director or non-10%-owner context.

Hard negatives: option exercises, tax withholding, gifts/grants/awards, planned 10b5-1 transactions, sales, 10% owner-only purchases that require separate review, indirect non-market transfers, and amended Form 4 duplicates.

## Lifecycle Status

- Scaffold: added `src/mre/insider_purchase_clusters.py` and corpus schema registration for `insider_purchase_clusters`.
- Source discovery: added SEC Form 4 / 4/A source-document builder over EDGAR submissions and primary XML documents.
- Parser: added Form 4 XML parser for transaction code, transaction date, acceptance time, owner role/title, shares, price, value, ownership after, direct/indirect ownership, derivative flag, footnotes, and 10b5-1 language.
- Review queue: parser emits event-compatible rows with `review_status=unreviewed` and source evidence; no machine row is model-ready.
- Parser audit: added gold-set validator with hard-negative false-positive gates. No reviewed gold set exists yet.
- Context enrichment: added transaction-value-to-market-cap, shares-purchased-to-shares-outstanding, 5-day and 10-day trailing cluster counts, 6-month prior purchase count, 20/60-day market-adjusted run-up, 52-week-high distance, and dollar-volume context.
- Timestamp and duplicate audit: added Form 4 filing timestamp checks and amended/same-owner duplicate detection.
- Readiness gates: added non-modeling gates for reviewed rows, primary purchases, officer/director rows, cluster rows, context coverage, timestamp clarity, duplicate audit, parser audit, execution survivability, and likely walk-forward out-of-sample count.
- First falsification: not eligible. Readiness fails before any return analysis.
- Fresh confirmation: not eligible.

## Execution Survivability Gate

Required before modeling: PASS.

Classification: delayed-digestion / slow-burn repricing candidate for open-market purchase clusters; explanation-only for hard negatives and non-market transactions.

Why it might remain tradeable after first realistic entry: insiders have already traded before Form 4 acceptance, so a tradable effect cannot be the trade itself. The only plausible tradable thesis is delayed market digestion of the public filing, role, transaction size, repeated purchases, drawdown context, and prior purchase history. Cluster confirmation may arrive over several filings, making this a slow-burn repricing candidate rather than a pure immediate-gap event.

First realistic entry: next open after SEC acceptance, or later if the filing is accepted after market close. Intraday acceptance needs separate execution review; daily OHLC alone cannot prove fill quality.

Required reporting if this ever reaches modeling:

- close-to-close abnormal behavior
- next-open behavior
- 25 bps, 50 bps, and 100 bps all-in cost stress
- explicit failure if next-open returns do not survive, even if close-to-close effects look explanatory

Current gate status: FAIL / not evaluated. No modeled results exist, and close-to-close explanatory effects must not be treated as tradable.

## Readiness Gates

- reviewed_usable_events_80_min: FAIL
- primary_open_market_purchase_events_60: FAIL
- officer_or_director_purchase_events_40: FAIL
- purchase_cluster_events_30: FAIL
- transaction_value_pct_market_cap_rows_40: FAIL
- pre_event_runup_rows_40: FAIL
- clear_filing_timestamps: FAIL
- duplicate_audit_pass: FAIL
- parser_audit_pass: FAIL
- execution_survivability_gate_pass: FAIL
- likely_oos_predictions_30: FAIL

## Pre-Registered Hypotheses

1. Multiple open-market officer/director purchases within 10 days are positive.
2. CEO/CFO purchases are stronger than director-only purchases.
3. Larger transaction value relative to market cap is stronger.
4. Purchases after drawdown or near a 52-week low differ from purchases after run-up.

## Next Required Work

1. Build a small/mid-cap-first Form 4 source corpus from 2018-present.
2. Human-review parser gold rows, including hard negatives for M, F, gifts/grants, 10b5-1 language, 10% owner-only rows, and 4/A duplicates.
3. Add point-in-time shares outstanding, market cap, price, volume, SPY, and sector ETF context.
4. Run parser, timestamp, duplicate, and execution survivability gates before any event-study or model.
5. Only if all readiness gates pass, run first falsification with close-to-close and next-open stress reported separately.
