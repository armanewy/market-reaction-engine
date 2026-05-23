# Agent 2K — Capital Raise Timestamp / Session Repair

## Verdict

**Timestamp repair passes as a data repair, but the prior 2H model result is invalid for graduation and the repaired corpus is not model-ready.**

The clean-slice timestamp problem found by Agent 2J was real. I rebuilt the 80-row clean-slice corpus with explicit timestamp provenance, strict session policy, and duplicate financing-cluster handling. After repair, only 59 rows remain model-eligible, with 58 event-study-usable rows and about 19 likely OOS predictions at `min_train=40`. That fails the modeling gate, so no model was trained.

## Timestamp Policy Applied

- `before_open`: same trading day reaction.
- `after_close`: next trading day reaction.
- `intraday`: marked ineligible because we only have daily prices.
- `unknown` or low-confidence timestamp: ineligible.
- duplicate same-financing filing cluster: only the canonical earliest event remains eligible.

## Timestamp Columns Added

The repaired audit files add:

- `event_time_original`
- `event_time_sec_acceptance`
- `event_time_press_release`
- `event_time_prospectus_supplement`
- `event_time_offering_pricing_announcement`
- `event_time_selected`
- `event_time_source`
- `release_session_original`
- `release_session_inferred`
- `release_session_selected`
- `timestamp_confidence`
- `timestamp_notes`
- `dedupe_group_id`
- `dedupe_status`
- `timestamp_policy_status`
- `model_eligible`

## Coverage

- Clean-slice rows audited: 80
- SEC acceptance timestamps available from local header or source manifest: 80
- Explicit press-release timestamps found: 0
- Explicit offering-pricing timestamps found: 0
- Model-eligible corrected rows: 59
- Deduplicated/rejected duplicate rows: 12

Selected sessions across all 80 rows:

{
  "after_close": 53,
  "before_open": 15,
  "intraday": 12
}

Timestamp policy outcomes:

{
  "ok": 59,
  "duplicate_same_financing_cluster": 12,
  "low_timestamp_confidence": 9
}

Selected timestamp source counts:

{
  "sec_acceptance": 38,
  "prospectus_supplement_sec_acceptance_from_source_manifest": 30,
  "prospectus_supplement_sec_acceptance": 12
}

Model-eligible session counts:

{
  "after_close": 46,
  "before_open": 13
}

## Readiness After Repair

- Reviewed usable rows: 59
- Completed financing rows: 59
- Rows with `financing_amount_pct_market_cap`: 52
- Rows with `discount_to_last_close_pct`: 47
- Event-study OK rows: 58
- Likely OOS predictions with `min_train=40`: 19

Decision: **do not train**. The repaired corpus fails reviewed-row, completed-financing-row, and likely-OOS gates.

## Event Study Only

| Dataset | OK rows | Mean H1 CAR | Median H1 CAR | Mean H3 CAR | Median H3 CAR | Positive H1 rate |
|---|---:|---:|---:|---:|---:|---:|
| original 2H event study | 79 | -0.0190 | -0.0103 | -0.0424 | -0.0335 | 0.405 |
| timestamp-repaired event study | 58 | -0.0179 | -0.0255 | -0.0356 | -0.0416 | 0.362 |

This is descriptive only. No new model, threshold tuning, or signal claim was made.

## Interpretation

Agent 2J already showed that the original AUC dropped from `0.699` to `0.506` when sessions were inferred. Agent 2K confirms the underlying cause: the original clean-slice corpus had `release_session=unknown` for every row and included intraday rows and duplicate filing clusters that should not have been model-eligible under daily-price rules.

The capital-raise clean slice can come back, but only after expanding the corrected timestamp-safe corpus. The next corpus build should target at least:

- 80+ corrected model-eligible rows
- 30+ likely OOS predictions at `min_train=40`
- explicit non-intraday session for every row
- duplicate financing clusters collapsed before event study/modeling

## Artifacts

- `data/events/capital_raise_clean_slice_timestamp_repair_audit.csv`
- `data/events/capital_raise_clean_slice_timestamp_dedupe_audit.csv`
- `data/events/capital_raise_clean_slice_timestamp_repaired_all.csv`
- `data/events/capital_raise_clean_slice_timestamp_repaired_model_events.csv`
- `data/events/capital_raise_clean_slice_timestamp_repaired_readiness_report.md`
- `artifacts/capital_raise_clean_slice_timestamp_repaired_event_study.csv`
- `artifacts/capital_raise_clean_slice_timestamp_repaired_event_study_summary.csv`
