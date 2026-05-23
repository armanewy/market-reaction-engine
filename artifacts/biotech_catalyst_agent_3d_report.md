# Agent 3D Biotech Catalyst First Falsification Pass

Decision: promising, require fresh-data confirmation.

This is a first falsification pass only. It is not a graduated signal, trading recommendation, or final empirical result.

## Inputs

- reviewed usable event rows: 97
- event-study ok rows: 97
- benchmark: SPY
- sector benchmark: XBI
- horizons: 1, 3, 10

## Walk-Forward And Costs

- predictions: 57
- ROC AUC: 0.629156010230179
- accuracy: 0.6491228070175439
- brier score: 0.2543844659074902
- ECE: 0.17498408687316275
- strategy trades: 50
- strategy long / short: 18 / 32
- mean net event return: 0.08019081968753466
- cumulative net return: 30.66527126138057
- null-shuffle p-value: 0.001996007984031936

## Hypothesis Checks

- h1_negative_binary_catalyst: n=34, h1_mean=-0.09501695952714354, h1_alignment=0.7352941176470589, h3_mean=-0.08880454371863758, h10_mean=-0.11689396051330982
- h2_positive_clinical_readout: n=5, h1_mean=-0.006880923131370155, h1_alignment=0.6, h3_mean=0.006485535117068404, h10_mean=-0.0017957639158221884
- h3_crl_halt_endpoint_failure: n=29, h1_mean=-0.10327288375928943, h1_alignment=0.7931034482758621, h3_mean=-0.10261641628687343, h10_mean=-0.12732243806476362
- h4_designation_only: n=9, h1_mean=0.004210364445787235, h1_alignment=None, h3_mean=-0.005912784623876857, h10_mean=-0.005483127848780678
- h5_positive_after_runup: n=23, h1_mean=0.05060777197133384, h1_alignment=None, h3_mean=0.0749248731711295, h10_mean=0.08856808028892318

## Controls

- random placebo h1 mean: 0.0021432329493209514
- shifted placebo h1 mean: -0.004335762858399863
- peer-control h1 mean: -0.0030540530083497898
- source-direction fixed strategy h1 mean net return: 0.044312163300844566

## Secondary Sector And Outliers

- IBB secondary h1 mean: -0.018696216446001362
- IBB secondary status: ok
- largest absolute h1 event share: 0.09654858870425909
- top five absolute h1 event share: 0.29259242070732266
- h1 mean excluding largest absolute event: -0.009154513466643168

## Interpretation

- Do not call the signal graduated from this first falsification pass.
- No parser labels were changed by this run.
- The walk-forward classifier targets h1 XBI-adjusted abnormal return direction and uses only pre-event/source-grounded features.
- IBB secondary control is optional and is not used for the primary decision unless separately inspected.

Do not graduate this signal from Agent 3D. A positive result would require fresh-data confirmation, stronger peer controls, timestamp audit, and repeated preregistered validation.
