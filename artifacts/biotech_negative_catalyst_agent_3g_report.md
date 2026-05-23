# Agent 3G Biotech Negative Catalyst Narrow Confirmation

Decision: timestamp issue found.

This is a narrow confirmation pass for negative binary biotech catalysts only. It does not change parser labels, tune thresholds, include positive readouts in the primary slice, or graduate a signal.

## Slice

- original negative-catalyst rows: 34
- fresh negative-catalyst rows: 27
- combined negative-catalyst rows: 61

## Base Rates

- fresh h1: n=27, mean=-0.1501147978143168, median=-0.0621697377643017, sign_accuracy=0.6666666666666666, winsorized_mean=-0.14926295738902726
- fresh h3: n=27, mean=-0.18993633367533405, median=-0.0963832669871214, sign_accuracy=0.7407407407407407, winsorized_mean=-0.19703062710636438
- fresh h10: n=27, mean=-0.1423653766373324, median=-0.0950850968118217, sign_accuracy=0.6296296296296297, winsorized_mean=-0.1584660755738984
- original h1: n=34, mean=-0.09501695952714352, median=-0.04908177275378445, sign_accuracy=0.7352941176470589, winsorized_mean=-0.07590291085274861
- original h3: n=34, mean=-0.08880454371863757, median=-0.05332595407566775, sign_accuracy=0.6764705882352942, winsorized_mean=-0.07488087204126335
- original h10: n=33, mean=-0.11689396051330977, median=-0.0912098893913487, sign_accuracy=0.7878787878787878, winsorized_mean=-0.11346847706473416
- combined h1: n=61, mean=-0.11940452729359727, median=-0.0508413293105955, sign_accuracy=0.7049180327868853, winsorized_mean=-0.09778834459531978
- combined h3: n=61, mean=-0.13356779501094584, median=-0.0752032415594843, sign_accuracy=0.7049180327868853, winsorized_mean=-0.12870831929853893
- combined h10: n=60, mean=-0.12835609776911994, median=-0.09331083967600201, sign_accuracy=0.7166666666666667, winsorized_mean=-0.1362583597409184

## Controls

- random placebo weaker than main h1 short rule: True
- shifted placebo weaker than main h1 short rule: True
- rotated peer weaker than main h1 short rule: True
- main h1 short mean net, 10 bps all-in: 0.07797988111591325
- random h1 short mean net, 10 bps all-in: 0.0004185334535171468
- shifted h1 short mean net, 10 bps all-in: -0.0007522370151478085
- peer h1 short mean net, 10 bps all-in: -0.001340959388584136

## Timestamp Safety

- rows audited: 61
- high-risk timestamp rows: 9
- medium-risk timestamp rows: 1
- reaction start before expected first tradable window: 9

## Execution And Outliers

- close-to-close 100 bps mean net: 0.06897988111591327
- next-open 25 bps mean net: 0.001416618616673811
- fresh h1 top 1 absolute share: 0.25952050304136487
- fresh h1 top 3 absolute share: 0.5924190613012196
- fresh h1 mean excluding top 1 absolute: -0.09857338598030206
- fresh h1 mean excluding top 3 absolute: -0.08257972553088223

## Calibration

Calibration is not applicable in Agent 3G because no probability model is trained. This pass intentionally uses a preregistered rule/base-rate slice after Agent 3E showed the broad probability model was poorly calibrated.

## Interpretation

- Do not call the signal graduated.
- No parser labels were changed.
- Positive clinical readouts and designation-only events are excluded from the primary slice.
- Daily OHLC data cannot prove intraday executable fills or trading-halt status.
