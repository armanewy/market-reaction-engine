# Market Reaction Engine

Version 0.5 adds a source-document extraction/provenance layer: raw filing/transcript/article manifests, deterministic evidence-grounded fact extraction, LLM work-packet preparation, and validated LLM fact ingestion.

This project is intentionally conservative. It is not a magic stock predictor. It is a point-in-time event-study workbench that helps answer:

> For this class of event, under this pre-event context, what abnormal market reactions have historically occurred?

The current pipeline is:

```text
curated/ingested event rows OR raw source-document manifests
→ evidence-grounded extracted facts
→ optional point-in-time expectation fields
→ local daily price data
→ pre-event expectation/context enrichment
→ event-study abnormal returns
→ chronological baseline model
→ walk-forward checks
→ analog retrieval and Markdown report
```

## Implemented milestones

### M0 — runnable project skeleton

- Python package under `src/mre`
- CLI entry point: `mre` or `python -m mre.cli`
- Synthetic offline demos
- Test suite

### M1 — event-study core

- Load curated point-in-time event CSVs
- Load local daily price CSVs
- Compute daily log returns
- Choose reaction start date based on `release_session`
  - `after_close` → next trading day
  - `before_open`, `intraday`, `unknown` → same trading day if available
- Fit a pre-event market model: `stock_return = alpha + beta * benchmark_return + residual`
- Compute raw, benchmark, expected, market-model, index-adjusted, and optional sector-adjusted returns
- Add z-scores and rough two-sided p-values

### M2 — data adapters

- `fetch-prices`: prototype daily prices via yfinance
- `sec-template`: generic SEC filings event-template generator
- `sec-earnings-corpus`: primary-source SEC 8-K Item 2.02 earnings candidates
- `earnings-corpus`: Alpha Vantage quarterly EPS history → earnings event rows
- `yfinance-earnings-corpus`: free/research bootstrap of historical earnings dates/EPS estimates

### M3 — modeling and analogs

- Chronological train/test baseline logistic model
- Walk-forward event-by-event direction evaluation
- Nearest-neighbor analog retrieval from event metadata and pre-event features
- Markdown report generation

### M4 — earnings expectations layer

- Built-in sector presets: `semis`, `semiconductors`, `mega_cap_tech`, `tech_platforms`, `software`, `cloud_software`, `biotech`, `banks`
- EPS estimate/surprise event rows
- External expectations template/merge flow
- Leakage guard for expectation timestamps after event timestamps
- Pre-event 5/20/60-day drift
- Market- and sector-adjusted pre-event drift
- Pre-event volatility
- Rolling beta and idiosyncratic volatility proxy
- Volume z-score
- Synthetic offline earnings demo

### M5 — richer point-in-time expectations

- Exact release-time template/merge flow that updates `event_time` and `release_session`
- Revenue, EPS, forward guidance, gross-margin, and forward gross-margin surprise features
- Option snapshot template and ATM-straddle implied-move estimator
- Analyst revision template and point-in-time revision feature builder
- Modeling feature list extended for implied move, margins, guidance, release-time quality, and analyst revision features
- Offline earnings demo now writes synthetic release-time, option-snapshot, and analyst-revision feeds

### M6 — source-document extraction/provenance layer

- Source-document manifest template with inline text or relative file paths
- Deterministic earnings/guidance fact extractor with evidence text and character offsets
- Extracted facts → expectation-feature rows
- Source documents → event rows
- JSONL extraction packets for external LLMs without calling an LLM
- Validator for external LLM fact JSONL that checks evidence appears in the source text
- Offline extraction demo

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

Run tests:

```bash
pytest -q
```

## Offline demos

Generic event-study demo:

```bash
mre demo --root .
```

Earnings/expectations demo:

```bash
mre earnings-demo --root .
```

Source-document extraction demo:

```bash
mre extraction-demo --root .
```

The extraction demo writes:

```text
data/extraction_demo/source_documents.csv
data/extraction_demo/docs/*.txt
data/extraction_demo/extracted_facts.csv
data/extraction_demo/extracted_expectations.csv
data/extraction_demo/extracted_events.csv
data/extraction_demo/extraction_diagnostics.json
```


The earnings demo writes:

```text
data/earnings_demo/earnings_events_raw.csv
data/earnings_demo/earnings_expectations.csv
data/earnings_demo/earnings_release_times.csv
data/earnings_demo/earnings_option_snapshots.csv
data/earnings_demo/earnings_analyst_revisions.csv
data/earnings_demo/earnings_events_enriched.csv
artifacts/earnings_demo_event_study.csv
artifacts/earnings_demo_model_report.json
artifacts/earnings_demo_walk_forward_predictions.csv
artifacts/earnings_demo_walk_forward_report.json
artifacts/earnings_demo_report.md
artifacts/earnings_demo_analogs.csv
```

## Earnings/guidance corpus starter

List presets:

```bash
mre sector-presets
```

Build an EPS-surprise corpus with Alpha Vantage:

```bash
export ALPHA_VANTAGE_API_KEY="your-key"

mre earnings-corpus \
  --preset semis \
  --start 2015-01-01 \
  --end 2025-01-01 \
  --out data/events/semis_earnings.csv
```

Notes:

- This is an MVP feed, not a trading-grade point-in-time estimates database.
- Alpha Vantage quarterly EPS history is useful because it includes reported EPS, estimated EPS, surprise, and surprise percentage.
- Release time is usually not precise enough in this feed for serious daily event studies. Curate `release_session` manually or use a higher-quality earnings-calendar/estimates vendor.

Alternative bootstrap using yfinance earnings dates:

```bash
mre yfinance-earnings-corpus \
  --preset semis \
  --start 2015-01-01 \
  --end 2025-01-01 \
  --out data/events/semis_yfinance_earnings.csv
```

This is convenient when you want to test plumbing without an Alpha Vantage key, but it is still not a verified point-in-time feed.

Build primary-source SEC earnings candidates instead:

```bash
export SEC_USER_AGENT="market-reaction-engine your-email@example.com"

mre sec-earnings-corpus \
  --preset semis \
  --start 2015-01-01 \
  --end 2025-01-01 \
  --out data/events/semis_sec_earnings_candidates.csv
```

Notes:

- SEC rows are better as primary-source event candidates.
- They do not contain analyst consensus, revenue surprise, guidance surprise, or options implied move unless you merge those later.

Fetch prototype prices and add pre-event context:

```bash
mre fetch-prices \
  --events data/events/semis_earnings.csv \
  --benchmark SPY \
  --start 2014-01-01 \
  --end 2025-01-01 \
  --out-dir data/prices/semis

mre enrich-expectations \
  --events data/events/semis_earnings.csv \
  --prices-dir data/prices/semis \
  --benchmark SPY \
  --out data/events/semis_earnings_enriched.csv
```

Run the event study/model/report:

```bash
mre run-event-study \
  --events data/events/semis_earnings_enriched.csv \
  --prices-dir data/prices/semis \
  --benchmark SPY \
  --horizons 1,3,10 \
  --out artifacts/semis_earnings_event_study.csv

mre walk-forward \
  --event-study artifacts/semis_earnings_event_study.csv \
  --horizon 1 \
  --min-train 40 \
  --out-predictions artifacts/semis_earnings_walk_forward_predictions.csv \
  --out-report artifacts/semis_earnings_walk_forward_report.json

mre report \
  --event-study artifacts/semis_earnings_event_study.csv \
  --horizon 1 \
  --out artifacts/semis_earnings_report.md
```


## Source-document extraction flow

Create a manifest for source documents. Each row can include inline `text` or a relative `path` to a text file:

```bash
mre source-docs-template --out data/events/source_documents.csv
```

Extract supported earnings/guidance facts with evidence spans:

```bash
mre extract-facts \
  --documents data/events/source_documents.csv \
  --facts-out data/events/extracted_facts.csv \
  --expectations-out data/events/extracted_expectations.csv \
  --events-out data/events/extracted_events.csv
```

Prepare JSONL packets for an external LLM extractor. This does not call an LLM; it creates auditable work units with a strict schema:

```bash
mre extraction-packets \
  --documents data/events/source_documents.csv \
  --out data/events/extraction_packets.jsonl
```

Validate external LLM fact rows before using them:

```bash
mre validate-llm-facts \
  --documents data/events/source_documents.csv \
  --llm-jsonl data/events/llm_facts.jsonl \
  --out data/events/validated_llm_facts.csv
```

The deterministic extractor is a transparent baseline, not a trading-grade parser. Treat extracted rows as reviewable candidates unless the source and evidence have been curated.

## External expectations flow

Create a template for point-in-time consensus/guidance/options data:

```bash
mre expectations-template \
  --events data/events/semis_earnings.csv \
  --out data/events/semis_expectations_template.csv
```

Fill the template with values known **before** `event_time`, then merge:

```bash
mre merge-expectations \
  --events data/events/semis_earnings.csv \
  --expectations data/events/semis_expectations_template.csv \
  --fill-labels \
  --out data/events/semis_earnings_with_expectations.csv
```

The merge command rejects expectation rows whose `asof_time` is after `event_time`.

## Richer expectation feeds

The new commands are intentionally vendor-neutral.  They let you ingest better paid/manual feeds without baking a questionable data vendor assumption into the model.

Curate exact release timestamps:

```bash
mre release-times-template \
  --events data/events/semis_earnings.csv \
  --out data/events/semis_release_times_template.csv

mre merge-release-times \
  --events data/events/semis_earnings.csv \
  --release-times data/events/semis_release_times_template.csv \
  --out data/events/semis_earnings_exact_times.csv
```

Add richer fundamentals expectations.  The external expectations CSV supports EPS, revenue, forward revenue guidance, forward EPS guidance, gross margin, and forward gross-margin guidance fields:

```bash
mre expectations-template \
  --events data/events/semis_earnings_exact_times.csv \
  --out data/events/semis_expectations_template.csv

mre merge-expectations \
  --events data/events/semis_earnings_exact_times.csv \
  --expectations data/events/semis_expectations_template.csv \
  --fill-labels \
  --out data/events/semis_earnings_fundamentals.csv
```

Estimate pre-event implied move from option snapshots.  Supply rows with `quote_time`, `expiration`, `underlying_price`, `strike`, and call/put mid or bid/ask columns.  The tool picks the nearest pre-event expiration/ATM strike and estimates implied move as `(call_mid + put_mid) / underlying_price`:

```bash
mre options-template \
  --events data/events/semis_earnings_fundamentals.csv \
  --out data/events/semis_options_template.csv

mre merge-options \
  --events data/events/semis_earnings_fundamentals.csv \
  --options data/events/semis_options_template.csv \
  --out data/events/semis_earnings_options.csv
```

Compute analyst revision features from point-in-time estimate rows:

```bash
mre analyst-revisions-template \
  --events data/events/semis_earnings_options.csv \
  --out data/events/semis_analyst_revisions_template.csv

mre merge-analyst-revisions \
  --events data/events/semis_earnings_options.csv \
  --revisions data/events/semis_analyst_revisions_template.csv \
  --windows 7,30 \
  --metrics eps,revenue,gross_margin,forward_revenue \
  --out data/events/semis_earnings_rich_expectations.csv
```

These commands still do not create trading-grade data by themselves.  They provide the ingestion and leakage-control plumbing for better point-in-time feeds.

## Generic event workflow

Create an event file:

```bash
mre make-template --out data/events/aapl_events.csv
```

Required columns:

| column | meaning |
|---|---|
| `event_id` | stable unique ID |
| `ticker` | company ticker |
| `event_time` | timestamp when the event became public/known |
| `event_type` | earnings, guidance, regulatory, product, lawsuit, security, etc. |
| `summary` | short point-in-time summary |

Useful optional columns:

| column | example |
|---|---|
| `release_session` | before_open, intraday, after_close, unknown |
| `expectedness` | expected, partial_surprise, surprise, unknown |
| `surprise_direction` | positive, negative, mixed, neutral, unknown |
| `surprise_magnitude` | low, medium, high, unknown |
| `materiality` | 0.0 to 1.0, assigned before looking at price reaction |
| `sector_benchmark` | XLK, XBI, XLF, SMH, QQQ, etc. |
| `source_type` | sec_filing, press_release, govt_release, transcript, etc. |
| `source_url` | source URL |

## Current limitations

- This is a research tool, not financial advice and not a production trading system.
- yfinance is only a prototype price source.
- Alpha Vantage EPS history is not enough by itself: add exact release timestamps, revenue/margin/guidance surprises, options implied move, and point-in-time analyst estimates.
- Most events should be noise. The correct system must abstain often.
- Before trusting a signal, add placebo dates, peer placebos, costs/slippage, and strict walk-forward validation.
