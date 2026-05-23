# M6/M7: Narrow-domain corpora and backtest falsification

This milestone moves the project from scaffolding into testable research workflows.

## M6: Narrow-domain corpus layer

The project now supports explicit corpus schemas for:

- `earnings_guidance`
- `fda_biotech`
- `regulatory_legal`
- `cyber_incident`
- `recall_safety`

These are not trading-grade datasets by themselves. They are schemas, validators,
and templates for building a reviewable corpus that can be fed into the event-study
and modeling pipeline.

Useful commands:

```bash
mre corpus-domains

mre domain-template \
  --domain fda_biotech \
  --tickers MRNA PFE BMY \
  --out data/events/fda_template.csv

mre build-corpus \
  --inputs data/events/fda_template_reviewed.csv \
  --domain fda_biotech \
  --corpus-name fda_catalysts_v1 \
  --out data/events/fda_catalysts_v1.csv

mre validate-corpus \
  --events data/events/fda_catalysts_v1.csv \
  --out artifacts/fda_catalysts_validation.csv
```

The validator checks for point-in-time review/evidence hygiene: timestamps, source
URLs, domain-required fields, review status, label quality, materiality, and source
evidence flags.

## M7: Backtest and falsification harness

The backtest harness adds:

- purged walk-forward validation
- calibration tables and expected calibration error
- event-level strategy simulation with costs/slippage
- return-shuffle null distributions
- random/shifted placebo event generation
- peer-control event generation
- domain base-rate tables

Useful commands:

```bash
mre purged-walk-forward \
  --event-study artifacts/event_study.csv \
  --horizon 1 \
  --min-train 40 \
  --purge-days 3 \
  --out-predictions artifacts/purged_predictions.csv \
  --out-report artifacts/purged_report.json

mre calibrate \
  --predictions artifacts/purged_predictions.csv \
  --out artifacts/calibration.csv

mre simulate-strategy \
  --predictions artifacts/purged_predictions.csv \
  --long-threshold 0.60 \
  --allow-short \
  --cost-bps 5 \
  --slippage-bps 5 \
  --out-trades artifacts/strategy_trades.csv \
  --out-report artifacts/strategy_report.json

mre null-shuffle \
  --predictions artifacts/purged_predictions.csv \
  --n-iter 500 \
  --long-threshold 0.60 \
  --allow-short \
  --out artifacts/null_shuffle_distribution.csv

mre research-backtest \
  --event-study artifacts/event_study.csv \
  --out-dir artifacts/research_backtest \
  --horizon 1 \
  --min-train 40 \
  --purge-days 3 \
  --probability-threshold 0.60 \
  --allow-short \
  --cost-bps 5 \
  --slippage-bps 5
```

Placebo controls:

```bash
mre make-placebo-events \
  --events data/events/curated_events.csv \
  --prices-dir data/prices \
  --out artifacts/placebo_events.csv \
  --n-per-event 2 \
  --mode random

mre make-peer-controls \
  --events data/events/curated_events.csv \
  --out artifacts/peer_control_events.csv
```

Then run the normal event-study command on those placebo/peer-control event files.

## Offline demo

```bash
mre corpus-demo --root .
```

This creates a synthetic multi-domain corpus, price files, event-study results,
placebo events, peer-control events, and a full research backtest folder.

## Honest limitations

This milestone does not solve market prediction. It gives the project a way to
build real corpora and then aggressively try to falsify any apparent signal. A
real edge still requires clean point-in-time data, no leakage, fresh validation,
realistic execution assumptions, and results that survive placebo/peer controls.
