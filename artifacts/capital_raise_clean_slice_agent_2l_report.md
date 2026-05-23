# Agent 2L Report - Capital Raise Repaired Slice Expansion

This is a data-readiness report, not a model result. No prediction model, threshold tuning, or backtest was run.

## Verdict

**model-ready after repair** for the minimum clean-slice gate. Agent 2M can run the corrected first falsification pass using this repaired v2 corpus.

Important caveat: the focused clean-slice parser audit remains 33/33 correct from Agent 2G and was reused as the parser audit basis here. The generic readiness helper expects 60 audit rows, so the preferred 60-row audit standard is still not met.

## Repaired V2 Corpus

- strict candidates audited: 127
- repaired model-eligible rows: 84
- net increase vs Agent 2K repaired rows: 25
- rows sourced from 2L expansion/enrichment files: 35
- completed financing rows: 84
- represented tickers: 37
- likely OOS predictions with min_train=40: 44
- rows with financing_amount_pct_market_cap: 84
- rows with discount_to_last_close_pct: 76
- rows with estimated_dilution_pct: 80

## Event Type Counts

- completed_equity_offering: 75
- registered_direct_offering: 9

## Session Counts

- after_close: 61
- before_open: 23

## Timestamp Policy Audit

- ok: 118
- duplicate_same_financing_cluster: 7
- intraday_daily_data_ambiguous: 2

Model rows use only `timestamp_policy_status = ok`, `duplicate_status = primary`, and `release_session_selected` in `{before_open, after_close}`. Intraday daily-bar rows remain ineligible rather than being forced into a reaction window.

## Duplicate Audit

- duplicate clusters identified: 7
- duplicate model rows: 0

Duplicate cluster examples:

- cr2l_0032: primary `BLNK_424B5_2023-02-06_0001493152-23-003705`, members=2
- cr2l_0033: primary `BLNK_8-K_2023-02-07_0001493152-23-003879`, members=2
- cr2l_0035: primary `BLNK_424B4_2025-12-11_0001493152-25-027305`, members=2
- cr2l_0061: primary `FATE_424B5_2021-01-07_0001193125-21-004330`, members=2
- cr2l_0073: primary `IONQ_424B5_2025-10-10_0001193125-25-236448`, members=2

## Parser Audit

- focused clean-slice audit rows: 33
- correct rows: 33
- accuracy: 1.000
- source: `data/events/capital_raise_parser_errors.csv` / `data/events/capital_raise_parser_audit_report.md`

## Minimum Gate Results

- 80+ repaired model-eligible rows: PASS
- 60+ completed financing rows: PASS
- 40+ financing_amount_pct_market_cap rows: PASS
- 40+ discount_to_last_close_pct rows: PASS
- 30+ likely OOS predictions with min_train=40: PASS
- focused clean-slice parser audit passes: PASS
- timestamp/session audit passes for model rows: PASS
- duplicate audit passes for model rows: PASS

## Preferred/Residual Gates

- 100+ repaired model-eligible rows: FAIL
- 60+ parser audit rows: FAIL

## Source Contribution

- `data\events\capital_raise_enriched.csv`: 49
- `data\events\capital_raise_clean_slice_2l_enriched_candidates.csv`: 18
- `data\events\capital_raise_clean_slice_2l_expansion_enriched_candidates.csv`: 11
- `data\events\capital_raise_clean_slice_2l_more2_enriched_candidates.csv`: 6

## Next Step

Run Agent 2M as the corrected first falsification pass, using only `data/events/capital_raise_clean_slice_timestamp_repaired_model_events_v2.csv`. Do not use the original Agent 2H result as current evidence, because that result collapsed under timestamp/session repair.
