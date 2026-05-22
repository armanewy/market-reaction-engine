# Milestones

## M0: Working skeleton

Status: implemented.

- Project layout
- CLI
- Synthetic demo
- Tests

## M1: Event-study engine

Status: implemented.

- Event CSV schema
- Local price CSVs
- yfinance prototype fetcher
- Market-model abnormal returns
- Benchmark/index-adjusted abnormal returns
- Sector-adjusted abnormal returns when sector benchmark is supplied
- Z-score and rough p-value

## M2: Candidate event ingestion

Status: partially implemented.

- SEC submissions template generator exists.
- It does not yet parse filing content or infer surprise/materiality.

Next:

- Parse filing documents.
- Compute filing diffs against prior 10-K/10-Q.
- Add primary-source evidence spans.

## M3: Analog retrieval and baseline model

Status: implemented.

- Nearest-neighbor event analogs
- Logistic baseline classifier
- Chronological split
- Markdown report

Next:

- Add walk-forward validation.
- Add calibration metrics.
- Add abstention thresholds.

## M4: Expectations layer

Status: not implemented.

This is the most important next milestone.

Potential features:

- Analyst consensus
- Company guidance
- Options implied move
- Pre-event drift
- Valuation multiple
- Volatility regime
- Short interest
- Sector/peer moves

## M5: LLM extraction layer

Status: not implemented.

Use LLMs only to convert documents into structured point-in-time facts. Do not let the LLM see the subsequent stock move.

## M6: Narrow-domain corpus

Status: not implemented.

Build one high-quality corpus before expanding:

- earnings/guidance events
- FDA/biotech events
- antitrust/regulatory events
- cyber breach events
- product recall events

## M7: Trading-grade backtest harness

Status: not implemented.

Required before taking any trading signal seriously:

- walk-forward validation
- transaction costs
- slippage
- position sizing
- placebo dates
- peer placebos
- feature pre-registration
- no lookahead data
