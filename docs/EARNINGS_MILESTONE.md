# Earnings / Guidance Corpus Milestone

This milestone adds the first narrow, real-data-oriented corpus path.

The goal is **not** to declare a tradable edge. The goal is to get a clean enough pipeline to ask:

> For recurring earnings events across comparable companies, how did EPS surprises and pre-event expectations line up with abnormal post-event reactions?

## Implemented

### 1. Sector presets

```bash
mre sector-presets
```

Built-in presets include semiconductors, mega-cap tech, software/cloud, biotech, and banks, with friendly aliases such as `semis`, `tech_platforms`, and `cloud_software`.

### 2. Alpha Vantage earnings corpus

```bash
export ALPHA_VANTAGE_API_KEY="your-key"

mre earnings-corpus \
  --preset semis \
  --start 2015-01-01 \
  --end 2025-01-01 \
  --out data/events/semis_earnings.csv
```

This converts quarterly EPS history into MRE event rows with reported EPS, estimated EPS, surprise, and surprise percentage.

Limitations:

- release timestamps/sessions still need curation;
- EPS surprise alone is weak;
- this is not an institutional point-in-time estimates dataset.

### 3. yfinance bootstrap corpus

```bash
mre yfinance-earnings-corpus \
  --preset semis \
  --start 2015-01-01 \
  --end 2025-01-01 \
  --out data/events/semis_yfinance_earnings.csv
```

This is a no-key bootstrap path for testing corpus plumbing. Treat it as research-only data until release timestamps and point-in-time estimates are independently verified.

### 4. SEC primary-source candidate corpus

```bash
export SEC_USER_AGENT="market-reaction-engine your-email@example.com"

mre sec-earnings-corpus \
  --preset semis \
  --start 2015-01-01 \
  --end 2025-01-01 \
  --out data/events/semis_sec_earnings_candidates.csv
```

This creates 8-K Item 2.02 earnings candidates from SEC submissions. These rows are primary-source candidates, not complete surprise labels.

### 5. Expectations/context enrichment

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

Added features include:

- pre-event 5/20/60-day return;
- market-adjusted 5/20/60-day return;
- sector-adjusted 5/20/60-day return when a sector benchmark is present;
- pre-event volatility;
- rolling beta and idiosyncratic volatility;
- pre-event volume z-score;
- EPS/revenue/guidance surprise features when expectation data exists;
- simple surprise-vs-runup score.

### 6. External expectations merge

```bash
mre expectations-template \
  --events data/events/semis_earnings.csv \
  --out data/events/semis_expectations_template.csv

mre merge-expectations \
  --events data/events/semis_earnings.csv \
  --expectations data/events/semis_expectations_template.csv \
  --fill-labels \
  --out data/events/semis_earnings_with_expectations.csv
```

The merge has a leakage guard: if an expectation row has `asof_time` after `event_time`, it errors.

### 7. Walk-forward validation

```bash
mre walk-forward \
  --event-study artifacts/semis_earnings_event_study.csv \
  --horizon 1 \
  --min-train 40 \
  --out-predictions artifacts/semis_walk_forward_predictions.csv \
  --out-report artifacts/semis_walk_forward_report.json
```

## Offline verification

```bash
mre earnings-demo --root .
```

This generates synthetic earnings events, expectation rows, prices, an enriched event file, event-study results, a walk-forward report, analogs, and a Markdown summary.

## Still missing before taking any signal seriously

1. Exact release timestamps/sessions for each event.
2. Revenue, margin, segment, and guidance surprise from point-in-time sources.
3. Options implied move and implied-volatility change.
4. Point-in-time analyst estimates with revision history.
5. Placebo dates and peer placebos.
6. Costs, slippage, and position-sizing assumptions.
7. Calibration and abstention thresholds.
