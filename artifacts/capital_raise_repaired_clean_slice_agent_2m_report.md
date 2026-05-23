# Agent 2M Report - Corrected Capital Raise Falsification Pass

This is the corrected first capital-raise falsification pass on the Agent 2L timestamp-repaired clean slice. It does not use the old Agent 2H result, does not tune thresholds, and does not graduate a signal.

## Decision

**failed falsification**. The repaired clean-slice h1 model does not reproduce the prior timestamp-suspect signal: AUC is below 0.50, ECE is high, mean net return is negative, and null-shuffle p-value is weak. h3 shows a better AUC, but it does not survive the null-shuffle gate and remains execution-fragile.

## Corpus Used

- input: `data/events/capital_raise_clean_slice_timestamp_repaired_model_events_v2.csv`
- event-study usable rows: 84
- universe: completed common-stock offerings / registered directs only
- exclusions preserved: ATMs, shelves, convertibles, capacity-only events, going-concern-only rows, ambiguous prospectus supplements, amendments without new financing

## Main Walk-Forward Results

| horizon | AUC | ECE | predictions | trades | mean net | median net | cumulative net | null p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| h1 | 0.448 | 0.345 | 43 | 33 | -0.0214 | -0.0008 | -0.5771 | 0.906 |
| h3 | 0.687 | 0.223 | 43 | 36 | 0.0088 | 0.0326 | -0.1427 | 0.407 |
| h10 | 0.586 | 0.256 | 43 | 38 | 0.0063 | 0.0186 | -0.1418 | 0.533 |

## Controls

| control | AUC | ECE | predictions | trades | mean net | cumulative net | null p |
|---|---:|---:|---:|---:|---:|---:|---:|
| random placebo h1 | 0.423 | 0.267 | 124 | 94 | -0.0056 | -0.4500 | 0.850 |
| shifted placebo h1 | 0.219 | 0.608 | 24 | 22 | -0.0111 | -0.2420 | 0.786 |
| peer h1 | 0.447 | 0.361 | 38 | 25 | -0.0221 | -0.4449 | 0.992 |

## Pre-Registered Hypothesis Base Rates

- hypothesis_discounted_after_runup: n=19, mean h1=0.0251, mean h3=0.0224, h1 negative rate=0.526
- hypothesis_large_financing: n=46, mean h1=-0.0159, mean h3=-0.0105, h1 negative rate=0.609
- hypothesis_combined_severity: n=12, mean h1=0.0312, mean h3=0.0500, h1 negative rate=0.500
- hypothesis_lower_severity_control: n=67, mean h1=-0.0273, mean h3=-0.0289, h1 negative rate=0.701

## Execution / Outlier Notes

- Close-to-close h1 is negative under every tested cost/slippage level.
- Next-open h1 is mixed-positive at lower cost levels, but it is a diagnostic lead using a different return definition, not a pass for the pre-registered close-to-close test.
- No-short / long-only variants do not repair the close-to-close h1 failure.
- Top-outlier removal does not convert the h1 result into a pass.

## Interpretation

The corrected timestamp/session policy was the decisive test. The old Agent 2H result remains archived as timestamp-suspect. Capital raises should not be graduated. If this domain continues, the next work should be diagnosis, not more modeling: inspect whether h3 reflects a real delayed reaction mechanism or just small-sample noise, and expand the repaired corpus before any second model pass.
