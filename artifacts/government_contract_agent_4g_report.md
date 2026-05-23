# Agent 4G Government Contract First Falsification Pass

Decision: failed falsification.

This is a first falsification pass only. Do not call the signal graduated.

## Inputs

- public-linked analysis events: 186
- event-study ok rows: 186
- small/mid-cap analysis rows: 38
- benchmark: SPY
- sector benchmark: SPY
- sector-control limitation: Defense/aerospace ETF prices were not available locally; SPY is used as the sector-control fallback.

## Walk-Forward And Costs

- predictions: 141
- ROC AUC: 0.4959758551307847
- accuracy: 0.5106382978723404
- brier score: 0.31324383440629305
- ECE: 0.19746141933075595
- strategy trades: 50
- mean net event return: -0.004218815770975572
- cumulative net return: -0.20111550269167888
- null-shuffle p-value: 0.7544910179640718

## Hypotheses

- h1_material_small_mid_award: n=26, h1_mean=0.020917361273633618, h1_positive_rate=0.6153846153846154, h3_mean=0.025031699835850407, h10_mean=0.0353680681246992
- h2_highly_material_small_mid_award: n=9, h1_mean=0.027475551553230067, h1_positive_rate=0.7777777777777778, h3_mean=0.032989282932143246, h10_mean=0.09785103802025055
- h3_large_prime_low_materiality_control: n=114, h1_mean=-0.0016664318699664785, h1_positive_rate=0.4824561403508772, h3_mean=-0.00204976438360082, h10_mean=-9.365956649451198e-05
- h4_ceiling_only_contrast: n=0, h1_mean=None, h1_positive_rate=None, h3_mean=None, h10_mean=None
- h5_positive_runup_material_award: n=28, h1_mean=0.013305246969737432, h1_positive_rate=0.5714285714285714, h3_mean=0.01903488779359926, h10_mean=-0.0004452536727701195

## Controls

- random placebo h1 mean: 0.0033637651242861555
- shifted placebo h1 mean: -0.0029479697516171565
- peer-control h1 mean: -8.440711569957669e-05

## Required Cautions

- Do not call the government-contract signal graduated from Agent 4G.
- USAspending remains economic verification only; public announcement timestamps drive event_time.
- GlobalSecurity mirrors were used only for machine-readable text during manifest buildout, not as timestamp authority.
- War.gov/DoD after-close announcements are measured from the next trading day by release_session handling.
- Sector-control ETF prices were unavailable unless noted; SPY fallback weakens sector-control interpretation.
