# Agent 2J — Capital Raise Leakage / Execution Audit

## Decision

**Result: timestamp issue found. Do not graduate the Agent 2H signal yet.**

The original 2H result survives several cost and no-short stress checks, but the timestamp audit found that all modeled rows had `release_session=unknown`. Based on SEC acceptance times, 49 of 79 event-study rows appear after-close, yet all 49 of those were measured from the same calendar date. Re-running with inferred sessions changes the walk-forward classification result materially.

## Original 2H Baseline

- ROC AUC: 0.699
- ECE: 0.196
- Mean net event return: 0.0448
- Null p-value: 0.0060
- Trades: 34

## Timestamp Stress

Using inferred sessions from SEC acceptance time:

- Main ROC AUC: 0.506
- Main ECE: 0.247
- Main mean net event return: 0.0391
- Main null p-value: 0.0160
- Placebo mean net event return: -0.0019
- Peer mean net event return: 0.0120

Interpretation: controls remain weaker than main on mean net return, but classification AUC drops near random and calibration worsens. The timestamp correction is therefore a serious robustness failure for the original 2H classification claim.

## Cost / Shorting Stress

| Variant | AUC | ECE | Trades | Long | Short | Mean Net | Cum Net | Null p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| original_short_cost_5 | 0.699 | 0.196 | 34 | 15 | 19 | 0.0448 | 2.7820 | 0.0060 |
| no_short_cost_5 | 0.699 | 0.196 | 15 | 15 | 0 | 0.0265 | 0.3322 | 0.0140 |
| short_cost_25 | 0.699 | 0.196 | 34 | 15 | 19 | 0.0408 | 2.3155 | 0.0060 |
| short_cost_50 | 0.699 | 0.196 | 34 | 15 | 19 | 0.0358 | 1.8104 | 0.0060 |
| short_cost_100 | 0.699 | 0.196 | 34 | 15 | 19 | 0.0258 | 1.0144 | 0.0060 |
| session_inferred_main | 0.506 | 0.247 | 35 | 10 | 25 | 0.0391 | 2.2639 | 0.0160 |
| session_inferred_placebo | 0.506 | 0.235 | 80 | 40 | 40 | -0.0019 | -0.2543 | 0.5848 |
| session_inferred_peer | 0.532 | 0.243 | 31 | 11 | 20 | 0.0120 | 0.3994 | 0.0938 |


The no-short version remains positive (`mean_net_event_return=0.0265`), which is encouraging. The short-enabled result remains positive under 25/50/100 bps cost+slippage stresses, though returns degrade.

## Liquidity / Shorting Realism

- Events audited: 80
- Rows with any low-liquidity or small-cap proxy flag: 20
- Rows with price below $5: 8
- Rows with median 20d dollar volume below $5M: 7
- Rows with market cap below $300M: 6

This confirms that execution realism matters. Short-enabled variants should not be trusted without borrow and spread data.

## Duplicate Audit

Potential same-ticker close-window duplicate clusters: 20 rows. These are not automatic rejects, but they need review before graduation because financing announcements, pricing supplements, and amendments can describe the same transaction.

## Feature Leakage Audit

- Rows with feature leakage flags: 45
- Intraday rows using same-day close as discount anchor: 26
- Rows with share-count filed after event: 0

## Verdict

**Continue, but block graduation until timestamp/session handling is fixed and rerun.**

The capital-raise clean slice remains interesting because it beats placebo/peer controls on the session-inferred mean-net stress and survives high cost stress. However, the original headline AUC does not survive next-open/session correction. The next required step is to rebuild the clean-slice corpus with explicit `release_session` from SEC acceptance time or press-release timestamp, then rerun 2H and 2I with those corrected sessions.

## Artifacts

- `artifacts/capital_raise_clean_slice_timestamp_audit.csv`
- `artifacts/capital_raise_clean_slice_duplicate_audit.csv`
- `artifacts/capital_raise_clean_slice_liquidity_audit.csv`
- `artifacts/capital_raise_clean_slice_cost_stress.csv`
- `artifacts/capital_raise_clean_slice_feature_leakage_audit.csv`
- `artifacts/capital_raise_clean_slice_session_inferred_events.csv`
- `artifacts/capital_raise_clean_slice_session_inferred_event_study.csv`
- `artifacts/backtest/capital_raise_clean_slice_audit/`
