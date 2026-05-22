# Market Reaction Engine

A conservative first build of the idea: a **point-in-time event-study workbench** for measuring how markets reacted to real-world events.

This is **not** a magic stock predictor. The initial goal is to build the data discipline and measurement layer that any serious prediction engine would need:

1. reliable event rows,
2. clean price data,
3. market/sector-adjusted abnormal returns,
4. historical analog retrieval,
5. simple baseline models that are easy to falsify.

The code runs fully offline with synthetic demo data, then can be pointed at real event CSVs and yfinance/SEC data.

---

## What is implemented in this version

### Milestone 0 — runnable project skeleton

- Python package under `src/mre`
- CLI entry point: `mre` or `python -m mre`
- Synthetic demo data generator
- Tests for the event-study and modeling pipeline

### Milestone 1 — event-study core

- Load curated point-in-time event CSVs
- Load local daily price CSVs
- Compute daily log returns
- Choose reaction start date based on release timing:
  - `after_close` → next trading day
  - `before_open`, `intraday`, `unknown` → same trading day if available
- Fit a pre-event market model:
  - `stock_return = alpha + beta * benchmark_return + residual`
- Compute event-window outputs:
  - raw returns
  - benchmark returns
  - expected returns
  - market-model cumulative abnormal returns
  - index-adjusted abnormal returns
  - optional sector-adjusted abnormal returns
  - z-scores and rough two-sided p-values

### Milestone 2 — data adapters

- `fetch-prices`: fetch daily prices via `yfinance` for prototyping
- `sec-template`: generate event-template rows from SEC submissions

Important: SEC-derived rows are templates. You still need to classify materiality, expectedness, and surprise direction before using them as modeling labels.

### Milestone 3 — baseline modeling and analogs

- Chronological train/test split
- Baseline logistic regression for positive/negative abnormal-return direction
- Nearest-neighbor analog retrieval using only pre-event/event metadata and pre-event features
- Markdown report generation

---

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

Run the full offline demo:

```bash
mre demo --root .
```

This creates:

```text
artifacts/demo_event_study.csv
artifacts/demo_model_report.json
artifacts/demo_report.md
artifacts/demo_analogs.csv
```

Or run each step manually:

```bash
mre init-demo --out data/demo

mre run-event-study \
  --events data/demo/events.csv \
  --prices-dir data/demo/prices \
  --benchmark SPY \
  --out artifacts/demo_event_study.csv

mre train \
  --event-study artifacts/demo_event_study.csv \
  --horizon 1 \
  --out-model artifacts/demo_reaction_direction.joblib \
  --out-report artifacts/demo_model_report.json

mre analogs \
  --event-study artifacts/demo_event_study.csv \
  --event-id demo_010 \
  --k 5 \
  --out artifacts/demo_analogs.csv

mre report \
  --event-study artifacts/demo_event_study.csv \
  --out artifacts/demo_report.md
```

---

## Using real data

### 1. Create an event file

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
| `materiality` | 0.0 to 1.0, manually assigned before looking at price reaction |
| `sector_benchmark` | XLK, XBI, XLF, etc. |
| `source_type` | sec_filing, press_release, govt_release, transcript, etc. |
| `source_url` | URL to primary source |

### 2. Fetch prices for the event tickers

```bash
mre fetch-prices \
  --events data/events/aapl_events.csv \
  --benchmark SPY \
  --start 2015-01-01 \
  --end 2025-01-01 \
  --out-dir data/prices
```

For serious research, replace yfinance with a point-in-time institutional data source. The price adapter is intentionally isolated in `src/mre/prices.py`.

### 3. Run event study

```bash
mre run-event-study \
  --events data/events/aapl_events.csv \
  --prices-dir data/prices \
  --benchmark SPY \
  --horizons 1,3,10 \
  --out artifacts/aapl_event_study.csv
```

### 4. Generate report and analogs

```bash
mre report \
  --event-study artifacts/aapl_event_study.csv \
  --horizon 1 \
  --out artifacts/aapl_report.md

mre analogs \
  --event-study artifacts/aapl_event_study.csv \
  --event-id YOUR_EVENT_ID \
  --k 10
```

---

## Generating SEC filing event templates

Set a proper User-Agent first:

```bash
export SEC_USER_AGENT="market-reaction-engine your-email@example.com"
```

Then:

```bash
mre sec-template \
  --ticker AAPL \
  --forms 8-K,10-Q,10-K \
  --limit 100 \
  --out data/events/aapl_sec_template.csv
```

This produces event rows from SEC submissions. Treat these as raw candidates, not final labels. A filing date alone does not say whether the content was material, surprising, positive, or negative.

---

## Data discipline rules

This project is only useful if you are strict about leakage.

1. **Do not label events using the subsequent price move.**
2. **Do not use articles published after the reaction window as event features.**
3. **Do not use revised macro data unless you intentionally model revised data.**
4. **Prefer primary sources for event facts.**
5. **Use chronological splits, not random splits.**
6. **Compare against dumb baselines.**
7. **Allow abstention. Most events should be noise.**

---

## What this is good for now

- Building a clean event/reaction memory
- Separating raw price moves from market/sector moves
- Finding historical analogs
- Ranking which event types historically mattered
- Building the first baseline models
- Discovering whether a narrower event class has signal

## What this is not good for yet

- Automated trading
- Intraday news reaction
- Options-aware expected moves
- Analyst-consensus surprise decomposition
- LLM-based event extraction from long documents
- Survivorship-bias-free institutional backtests
- Any claim of alpha

---

## Next milestones I would build

### Milestone 4 — expectations layer

Add point-in-time expectations:

- analyst EPS/revenue consensus
- company guidance
- options implied move
- pre-event run-up
- valuation regime
- short interest / positioning proxies

### Milestone 5 — event extraction layer

Use an LLM only for structured extraction, not final prediction:

```json
{
  "event_type": "guidance",
  "claims": [
    {
      "claim": "Revenue guidance was below consensus",
      "source_span": "...",
      "numeric_delta": "...",
      "confidence": 0.91
    }
  ]
}
```

### Milestone 6 — narrow-domain models

Pick one event family across many comparable companies:

- earnings guidance cuts among SaaS companies
- FDA catalysts in biotech
- antitrust/regulatory events for mega-cap tech
- product recall events in autos/consumer hardware
- cyber incidents in public companies

### Milestone 7 — proper backtest harness

- walk-forward validation
- transaction costs/slippage
- pre-registered features
- placebo dates
- peer-placebo events
- benchmark comparisons
- calibration plots

---

## Project layout

```text
src/mre/
  cli.py            CLI commands
  demo.py           offline synthetic demo data
  events.py         event CSV schema/validation
  prices.py         local/yfinance price adapters
  event_study.py    abnormal-return engine
  modeling.py       baseline classifier + analog search
  reports.py        Markdown report generation
  sec.py            SEC submissions template generation

docs/
  DESIGN.md
  MILESTONES.md
  DATA_DISCIPLINE.md

tests/
  test_event_study.py
  test_modeling.py
```

