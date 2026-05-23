# Agent 3J Corrected Biotech Negative-Catalyst Confirmation

Decision: execution unrealistic.

This is the first clean confirmation test for the timestamp-repaired negative binary biotech catalyst slice. It does not tune thresholds, change parser labels, add positive readouts, include designation-only events, or graduate a signal.

## Slice

- corrected eligible rows: 61
- fresh rows: 27
- original rows: 34
- event-study ok rows: 61

## XBI-Adjusted Base Rates

- fresh h1: n=27, mean=-0.17975140838829554, median=-0.028595494948143913, sign_accuracy=0.6666666666666666, winsorized_mean=-0.18865844279342114
- fresh h3: n=27, mean=-0.17319991965182346, median=-0.07520324155948438, sign_accuracy=0.7407407407407407, winsorized_mean=-0.17317076454625582
- fresh h10: n=27, mean=-0.1264136916620076, median=-0.04400319197289541, sign_accuracy=0.5925925925925926, winsorized_mean=-0.1396463752209908
- original h1: n=34, mean=-0.09501695952714354, median=-0.0490817727537845, sign_accuracy=0.7352941176470589, winsorized_mean=-0.07590291085274864
- original h3: n=34, mean=-0.08880454371863758, median=-0.05332595407566779, sign_accuracy=0.6764705882352942, winsorized_mean=-0.07488087204126335
- original h10: n=33, mean=-0.11689396051330982, median=-0.09120988939134873, sign_accuracy=0.7878787878787878, winsorized_mean=-0.11346847706473422
- combined h1: n=61, mean=-0.1325223713181452, median=-0.04732221619697345, sign_accuracy=0.7049180327868853, winsorized_mean=-0.129479194928868
- combined h3: n=61, mean=-0.12615987404971984, median=-0.056304170385880294, sign_accuracy=0.7049180327868853, winsorized_mean=-0.12036235641513819
- combined h10: n=60, mean=-0.12117783953022382, median=-0.08710766371358153, sign_accuracy=0.7, winsorized_mean=-0.12729250521754515

## Controls

- random placebo weaker than main h1 short rule: True
- shifted placebo weaker than main h1 short rule: True
- rotated peer weaker than main h1 short rule: True
- main h1 short mean net, 10 bps all-in: 0.0846900838865975
- random h1 short mean net, 10 bps all-in: 0.012129848331763384
- shifted h1 short mean net, 10 bps all-in: -0.0051690637792794186
- peer h1 short mean net, 10 bps all-in: 0.002040339294439355

## Timestamp And Execution

- reaction starts before first tradable window: 0
- ambiguous timestamp rows: 0
- duplicate rows: 0
- close-to-close 100 bps mean net: 0.07569008388659752
- next-open 25 bps mean net: -0.004389230895686009
- next-open trades: 61

## Outliers

- fresh h1 top 1 absolute share: 0.22412341167824462
- fresh h1 top 3 absolute share: 0.5694167466234454
- fresh h1 mean excluding top 1 absolute: -0.12934986619174155
- fresh h1 mean excluding top 3 absolute: -0.044468705443483116

## Calibration

Calibration is not applicable because Agent 3J uses a preregistered negative-catalyst rule/base-rate slice and trains no probability model.

No signal is graduated from this corrected confirmation pass.
