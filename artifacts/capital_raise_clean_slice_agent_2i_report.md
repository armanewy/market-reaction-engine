# Agent 2I — Capital Raise Fresh-Data Confirmation

## Decision

**Promising but underpowered. Fresh confirmation did not run.**

The existing unused clean-slice candidates did not meet the minimum fresh-data gate. I excluded every event from `data/events/capital_raise_clean_slice_model_events.csv`, kept only completed common-stock offerings / registered directs, inferred release sessions from SEC acceptance timestamps, and enriched point-in-time share context where available.

## Fresh Corpus

- Fresh reviewed usable rows: 32
- Fresh completed financing rows: 32
- Fresh tickers: 16
- Rows with `financing_amount_pct_market_cap`: 7
- Rows with `discount_to_last_close_pct`: 13
- Event-study usable rows: 22
- Likely OOS predictions with `min_train=40`: 0

Minimum gate result: **failed**.

| Gate | Required | Actual | Pass |
|---|---:|---:|---|
| fresh reviewed usable rows | 40 | 32 | no |
| completed financing rows | 30 | 32 | yes |
| market-cap severity rows | 25 | 7 | no |
| discount rows | 25 | 13 | no |
| likely OOS predictions | 20 | 0 | no |

## Descriptive Event Study

The fresh event study is descriptive only because it has too few usable rows for walk-forward validation.

- Fresh event-study OK rows: 22
- Mean H1 market-model CAR: -0.0211
- Mean H3 market-model CAR: -0.0169
- Placebo OK rows: 64
- Peer OK rows: 9

The main fresh backtest was blocked by the harness: fewer than `min_train=40` usable events.

## Placebo/Peer Notes

Placebo controls were generated and the placebo backtest ran because it had 64 OK rows. That result is not a substitute for main fresh confirmation.

- Placebo ROC AUC: 0.579
- Placebo ECE: 0.355
- Placebo mean net event return: 0.0038
- Placebo null p-value: 0.4172

Peer controls produced only 9 usable rows and were also underpowered.

## Verdict

**Promising but underpowered.**

This does not confirm or refute the Agent 2H candidate signal. It says the existing unused candidate pool is insufficient for fresh confirmation. The next fresh-data attempt needs a targeted source expansion that adds new clean-slice events with both price/discount and market-cap/share-count context, preferably from tickers not represented in the original 80-row slice.

## Artifacts

- `data/events/capital_raise_clean_slice_fresh_reviewed.csv`
- `data/events/capital_raise_clean_slice_fresh_enriched.csv`
- `data/events/capital_raise_clean_slice_fresh_readiness_report.md`
- `data/events/capital_raise_clean_slice_fresh_parser_audit_report.md`
- `artifacts/capital_raise_clean_slice_fresh_event_study.csv`
- `artifacts/capital_raise_clean_slice_fresh_backtest_report.json`
- `artifacts/capital_raise_clean_slice_fresh_placebo_report.json`
- `artifacts/capital_raise_clean_slice_fresh_peer_report.json`
