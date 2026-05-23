# Capital Raise Repaired Clean Slice Execution Stress

This stress report applies the frozen Agent 2M h1 walk-forward probabilities. It is not a new tuned model.

## close_to_close_h1

| shorting | total bps | trades | mean net | median net | hit rate | cumulative net |
|---|---:|---:|---:|---:|---:|---:|
| True | 5 | 33 | -0.0209 | -0.0003 | 0.485 | -0.5699 |
| False | 5 | 14 | -0.0451 | -0.0134 | 0.286 | -0.5064 |
| True | 25 | 33 | -0.0229 | -0.0023 | 0.485 | -0.5982 |
| False | 25 | 14 | -0.0471 | -0.0154 | 0.286 | -0.5208 |
| True | 50 | 33 | -0.0254 | -0.0048 | 0.455 | -0.6311 |
| False | 50 | 14 | -0.0496 | -0.0179 | 0.286 | -0.5382 |
| True | 100 | 33 | -0.0304 | -0.0098 | 0.455 | -0.6892 |
| False | 100 | 14 | -0.0546 | -0.0229 | 0.286 | -0.5714 |

## next_open_h1

| shorting | total bps | trades | mean net | median net | hit rate | cumulative net |
|---|---:|---:|---:|---:|---:|---:|
| True | 5 | 33 | 0.0094 | 0.0125 | 0.515 | 0.3153 |
| False | 5 | 14 | 0.0167 | -0.0064 | 0.429 | 0.2354 |
| True | 25 | 33 | 0.0074 | 0.0105 | 0.515 | 0.2318 |
| False | 25 | 14 | 0.0147 | -0.0084 | 0.429 | 0.2017 |
| True | 50 | 33 | 0.0049 | 0.0080 | 0.515 | 0.1346 |
| False | 50 | 14 | 0.0122 | -0.0109 | 0.429 | 0.1608 |
| True | 100 | 33 | -0.0001 | 0.0030 | 0.515 | -0.0379 |
| False | 100 | 14 | 0.0072 | -0.0159 | 0.429 | 0.0828 |

## Interpretation

- Close-to-close h1 is negative under every tested cost/slippage level.
- Next-open h1 is mixed-positive at lower cost levels, but this uses the same close-to-close-trained probabilities against a different execution-return definition. Treat it as a diagnostic lead, not a signal pass.
- No-short / long-only does not repair the close-to-close h1 failure.

## Outlier Robustness Snapshot

| scope | horizon | variant | n | mean | median | sign rate |
|---|---|---|---:|---:|---:|---:|
| event_study | h1 | all | 84 | -0.0149 | -0.0173 | 0.631 |
| event_study | h1 | drop_abs_top1 | 83 | -0.0188 | -0.0185 | 0.639 |
| event_study | h1 | drop_abs_top3 | 81 | -0.0203 | -0.0185 | 0.642 |
| event_study | h1 | winsor_5_95 | 84 | -0.0192 | -0.0173 | 0.631 |
| event_study | h3 | all | 84 | -0.0131 | -0.0140 | 0.560 |
| event_study | h3 | drop_abs_top1 | 83 | -0.0197 | -0.0162 | 0.566 |
| event_study | h3 | drop_abs_top3 | 81 | -0.0121 | -0.0118 | 0.556 |
| event_study | h3 | winsor_5_95 | 84 | -0.0149 | -0.0140 | 0.560 |
| event_study | h10 | all | 84 | -0.0100 | -0.0384 | 0.583 |
| event_study | h10 | drop_abs_top1 | 83 | -0.0228 | -0.0402 | 0.590 |
| event_study | h10 | drop_abs_top3 | 81 | -0.0396 | -0.0461 | 0.605 |
| event_study | h10 | winsor_5_95 | 84 | -0.0252 | -0.0384 | 0.583 |
| strategy_trades | h1 | all | 33 | -0.0214 | -0.0008 | 0.485 |
| strategy_trades | h1 | drop_abs_top1 | 32 | -0.0123 | 0.0009 | 0.500 |
| strategy_trades | h1 | drop_abs_top3 | 30 | 0.0000 | 0.0074 | 0.533 |
| strategy_trades | h1 | winsor_5_95 | 33 | -0.0181 | -0.0008 | 0.485 |
| strategy_trades | h3 | all | 36 | 0.0088 | 0.0326 | 0.694 |
| strategy_trades | h3 | drop_abs_top1 | 35 | 0.0244 | 0.0335 | 0.714 |
| strategy_trades | h3 | drop_abs_top3 | 33 | 0.0283 | 0.0335 | 0.727 |
| strategy_trades | h3 | winsor_5_95 | 36 | 0.0157 | 0.0326 | 0.694 |
| strategy_trades | h10 | all | 38 | 0.0063 | 0.0186 | 0.579 |
| strategy_trades | h10 | drop_abs_top1 | 37 | -0.0046 | 0.0177 | 0.568 |
| strategy_trades | h10 | drop_abs_top3 | 35 | 0.0117 | 0.0196 | 0.600 |
| strategy_trades | h10 | winsor_5_95 | 38 | 0.0034 | 0.0186 | 0.579 |