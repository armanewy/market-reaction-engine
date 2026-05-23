# Agent 3I Biotech Negative Catalyst Timestamp Repair

Decision: timestamp repair passes, ready for corrected confirmation.

This is a timestamp repair and audit pass for the frozen negative binary biotech catalyst slice. It does not train a model, tune thresholds, or change parser labels.

## Timestamp Repair

- total rows: 61
- repaired eligible rows: 61
- fresh repaired eligible rows: 27
- original repaired eligible rows: 34
- original pre-window leakage rows found: 9
- rows repaired by shifting to first tradable window: 9
- rows dropped for unrepaired pre-window leakage: 0
- ambiguous timestamp rows: 0
- duplicate rows: 0
- likely OOS predictions after repair, min_train=40: 21

## Descriptive Returns

- fresh h1: n=27, mean=-0.17975140838829554, median=-0.028595494948143913, sign_accuracy=0.6666666666666666, winsorized_mean=-0.18865844279342114
- fresh h3: n=27, mean=-0.1731999196518235, median=-0.0752032415594843, sign_accuracy=0.7407407407407407, winsorized_mean=-0.17317076454625582
- fresh h10: n=27, mean=-0.12641369166200772, median=-0.04400319197289559, sign_accuracy=0.5925925925925926, winsorized_mean=-0.13964637522099088
- original h1: n=34, mean=-0.09501695952714354, median=-0.0490817727537845, sign_accuracy=0.7352941176470589, winsorized_mean=-0.07590291085274864
- original h3: n=34, mean=-0.08880454371863755, median=-0.05332595407566789, sign_accuracy=0.6764705882352942, winsorized_mean=-0.07488087204126334
- original h10: n=33, mean=-0.1168939605133098, median=-0.09120988939134869, sign_accuracy=0.7878787878787878, winsorized_mean=-0.11346847706473419
- combined h1: n=61, mean=-0.1325223713181452, median=-0.04732221619697345, sign_accuracy=0.7049180327868853, winsorized_mean=-0.129479194928868
- combined h3: n=61, mean=-0.12615987404971984, median=-0.05630417038588027, sign_accuracy=0.7049180327868853, winsorized_mean=-0.12036235641513819
- combined h10: n=60, mean=-0.12117783953022387, median=-0.08710766371358167, sign_accuracy=0.7, winsorized_mean=-0.12729250521754518

## Policy

- before_open uses the same trading day when available.
- after_close uses the next trading day.
- intraday rows are conservatively shifted to the next trading day because local data is daily OHLC only.
- Rows with missing source timestamps or no first-tradable trading day are not model eligible.
- Duplicate non-canonical rows are not model eligible.

No signal is graduated from this timestamp repair pass.
