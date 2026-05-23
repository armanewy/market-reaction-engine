# Milestones

## M0: Working skeleton

Status: implemented.

- Project layout
- CLI
- Synthetic demos
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

Implemented:

- SEC submissions template generator
- SEC 8-K Item 2.02 earnings-candidate corpus
- Alpha Vantage quarterly EPS-history corpus
- yfinance earnings-date/EPS bootstrap corpus

Next:

- Parse filing/transcript content.
- Compute filing diffs against prior 10-K/10-Q.
- Add primary-source evidence spans.

## M3: Analog retrieval and baseline model

Status: implemented.

- Nearest-neighbor event analogs
- Logistic baseline classifier
- Chronological split
- Walk-forward validation command
- Markdown report

Next:

- Add calibration curves.
- Add abstention thresholds.
- Add placebo controls.

## M4: Expectations layer

Status: started/implemented as MVP.

Implemented:

- EPS estimate/surprise fields from an earnings corpus
- External expectation template/merge flow
- Leakage guard for expectation `asof_time`
- Pre-event drift over 5/20/60 trading days
- Market-adjusted and sector-adjusted pre-event drift
- Pre-event volatility
- Rolling beta/idiosyncratic volatility proxy
- Pre-event volume z-score
- Simple surprise-vs-runup score

Still missing:

- Options implied move
- Revenue/margin/segment/guidance surprise from real point-in-time feeds
- Institutional point-in-time analyst estimates
- Valuation multiple
- Short interest
- Peer-basket reaction context

## M5: Richer point-in-time expectations

Status: implemented in v0.4.0.

- Exact release timestamp merge flow
- Revenue/EPS/gross-margin/guidance surprise fields
- ATM-straddle implied-move ingestion from option snapshots
- Analyst revision feature builder
- Richer synthetic earnings demo

See `docs/RICH_EXPECTATIONS_MILESTONE.md`.

## M6: Source-document extraction/provenance layer

Status: implemented in v0.5.0.

Use extraction only to convert documents into structured point-in-time facts. Do not let extractors see subsequent stock moves.

- Source-document manifest template
- Deterministic regex baseline for earnings/guidance facts
- Evidence text and character offsets for every fact
- Fact rows pivoted into expectation rows
- Source documents converted into event rows
- JSONL packet builder for external LLM extraction
- Validator for external LLM fact rows that checks evidence appears in the source text

See `docs/EXTRACTION_MILESTONE.md`.

## M6: Narrow-domain corpora

Status: earnings started.

Implemented in v0.2:

- Earnings/EPS-surprise event corpus path using Alpha Vantage and yfinance as prototype providers
- Primary-source SEC earnings-candidate corpus path
- Built-in sector presets for comparable-company corpora
- Offline synthetic earnings demo

Next corpora to consider after earnings:

- FDA/biotech events
- antitrust/regulatory events
- cyber breach events
- product recall events

## M7: Real source ingestion

Status: implemented in v0.6.0.

This milestone turns the extraction/provenance layer into a source-ingestion pipeline.

- URL/local/inline source-ingestion template
- Normalize company press releases, transcript pages, agency docs, or local HTML/text into auditable text files
- SEC filing source-document ingestion
- SEC archive index support for primary filing docs and likely earnings-release exhibits
- 8-K Item 2.02 default filter for earnings candidates
- Source manifest output compatible with `mre extract-facts`
- Offline source-ingestion demo chaining ingestion → extraction

See `docs/SOURCE_INGESTION_MILESTONE.md`.


## M8: Trading-grade backtest harness

Status: not implemented.

Required before taking any trading signal seriously:

- placebo dates
- peer placebos
- transaction costs
- slippage
- position sizing
- calibration/abstention
- strict point-in-time data handling
- pre-registered feature sets

