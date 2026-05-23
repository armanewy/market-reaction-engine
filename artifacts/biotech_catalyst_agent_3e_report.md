# Agent 3E Biotech Fresh-Data Confirmation

Decision: failed fresh confirmation.

This is a fresh-data confirmation pass only. It is not a graduated signal, trading recommendation, or final empirical result.

## Fresh Holdout

- source: new tickers outside Agent 3D, parsed by fixed 3C parser and strict 3E rule review
- fresh reviewed usable rows: 67
- fresh binary catalysts: 47
- fresh negative catalysts: 27
- fresh positive/contrast rows: 40
- market-cap context rows: 66
- XBI run-up context rows: 67
- likely OOS predictions: 27

## Walk-Forward, Calibration, Costs

- predictions: 27
- ROC AUC: 0.6813186813186813
- accuracy: 0.7037037037037037
- brier score: 0.24245323402683672
- ECE: 0.28245316582993396
- strategy trades: 24
- mean net event return: 0.12343383021896552
- cumulative net return: 8.094021027745404
- null-shuffle p-value: 0.023952095808383235

## Hypothesis Slices

- h1_negative_binary_catalyst: n=27, h1_mean=-0.15011479781431677, h3_mean=-0.18993633367533405, h10_mean=-0.1423653766373324
- h2_positive_clinical_readout: n=7, h1_mean=-0.14639887084718245, h3_mean=-0.16859850884446548, h10_mean=-0.14914595493783483
- h3_crl_halt_endpoint_failure: n=18, h1_mean=-0.1899232477593471, h3_mean=-0.2291207162466895, h10_mean=-0.1440502196087894
- h4_designation_only: n=7, h1_mean=-0.0051736655018822806, h3_mean=0.023237516257510523, h10_mean=0.03821802940104898
- h5_positive_after_runup: n=9, h1_mean=0.06718032417170527, h3_mean=0.11202759217319619, h10_mean=0.11469869004923655

## Controls And Robustness

- random placebo h1 mean: 0.004383587927187723
- shifted placebo h1 mean: -0.0004181712558991243
- peer-control h1 mean: -0.011147885819801558
- h1 exclude top 1 absolute mean: -0.046946598239503895
- h1 exclude top 3 absolute mean: -0.017244600595639342
- h1 exclude top 5 absolute mean: -0.018906135185554396
- h1 winsorized mean 5/95: -0.04748365941989503
- h1 sign accuracy, directional rows only: 0.58

## Gates

- fresh_reviewed_usable_rows_40: PASS
- fresh_binary_catalyst_rows_25: PASS
- fresh_negative_catalyst_rows_15: PASS
- fresh_positive_or_contrast_rows_15: PASS
- fresh_market_cap_context_rows_25: PASS
- fresh_xbi_runup_context_rows_25: PASS
- fresh_likely_oos_predictions_20: PASS
- parser_audit_remains_passing: PASS
- timestamps_reviewed: PASS

Do not call the signal graduated. Agent 3E only tests whether the Agent 3D result survives a separate fresh-data pass.

- Do not call the signal graduated from this fresh-data confirmation pass.
- No parser labels were changed by this run.
- The walk-forward classifier uses the same h1 XBI-adjusted target and fixed feature setup as Agent 3D.
- Fresh rows are rule-reviewed SEC 8-K/exhibit events from new tickers, not a fully human-reviewed corpus.