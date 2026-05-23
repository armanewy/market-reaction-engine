# Agent 3F Biotech Leakage, Timestamp, and Outlier Audit

Decision: result weakened but still promising.

This audit tries to break the Agent 3D result. It does not change parser labels, tune thresholds, or graduate the signal.

## Timestamp Audit

- rows audited: 97
- high-risk timestamp rows: 0
- medium-risk timestamp rows: 5
- session mismatches: 58
- reaction start before expected first tradable window: 0

## Duplicate Audit

- rows audited: 97
- high-risk duplicate rows: 0
- source mirror rows: 86
- prior-announcement language rows: 0
- conference/publication language rows: 39

## Outliers

- top 1 absolute h1 share: 0.09654858870425914
- top 3 absolute h1 share: 0.2234687954593378
- top 5 absolute h1 share: 0.29259242070732283
- top ticker: XENE (0.13071537561116328)
- CRL / halt / failure absolute h1 share: 0.39619758004027705

## Liquidity And Execution

- events audited: 97
- high-risk liquidity rows: 0
- medium/high liquidity rows: 36
- price under $5 rows: 3
- gap >= 20% rows: 15
- close-to-close 100 bps mean net: 0.07119081968753466
- next-open 25 bps mean net: 0.007094561343886414

## Matched Peer Control

- matched peer rows: 97
- main h1 mean: -0.01929923292494176
- matched peer h1 mean: -0.00032923296285220356
- main h1 mean abs: 0.10605122273877503
- matched peer h1 mean abs: 0.023446332372214967

## Interpretation

- Daily OHLC cannot prove intraday executable prices or exchange trading halt status.
- SEC exhibit acceptance is used as the best available press-release timestamp when a separate wire timestamp is absent.
- Matched peer control is approximate: market-cap/stage/XBI-beta matching uses available local event and price data, not a hand-curated mechanism peer basket.
- This is not a graduated signal.

Do not graduate the biotech signal from this audit. Agent 3F is a break-the-result pass; fresh-data confirmation and a deeper timestamp/execution review remain separate requirements.