# Automation Pipeline Milestone

This milestone turns the project into a repeatable research loop.  The goal is not
hands-off trading.  The goal is to make it cheap to build candidate corpora, force
evidence review, and then try to break apparent signals with placebo, peer-control,
calibration, null-shuffle, and cost/slippage tests.

## The loop

```text
source candidates
→ source/extraction evidence
→ review queue
→ curated corpus
→ prices + pre-event context
→ event study
→ placebo/peer controls
→ purged walk-forward backtest
→ calibration + costs/slippage + null shuffle
→ gated research report
```

## Create a run config

```bash
mre pipeline-template \
  --run-id semis_earnings_v1 \
  --domain earnings_guidance \
  --preset semiconductors \
  --source-mode yfinance_earnings \
  --out research/semis_earnings_v1.json
```

Then edit the JSON.  For serious work, add point-in-time expectation files such as
release times, options snapshots, analyst revisions, and manually reviewed labels.

## Run the pipeline

```bash
mre run-pipeline --config research/semis_earnings_v1.json
```

Outputs are written under:

```text
runs/<run_id>/
  data/events/
  data/source_docs/
  data/prices/
  artifacts/
  pipeline_report.json
  research_report.md
```

## Review gate

The pipeline always creates a review queue:

```text
runs/<run_id>/data/events/03_review_queue.csv
```

For real research, edit that file and mark trustworthy rows as reviewed/accepted.
Then rerun with:

```json
{
  "source": {
    "mode": "manual_events",
    "events_csv": "runs/<run_id>/data/events/03_review_queue.csv"
  },
  "corpus": {
    "require_reviewed": true
  }
}
```

This avoids quietly promoting unreviewed scraped/extracted rows into a trusted corpus.

## Offline demo

```bash
mre pipeline-demo --root .
```

This uses synthetic data and existing local price CSVs.  It is only a machinery test.

## Interpreting the decision

`research_report.md` contains a decision such as:

- `promising_needs_fresh_data`: passed the configured gates, but still needs fresh unseen data.
- `not_promising_yet`: one or more gates failed.
- `failed_control_test`: placebo or peer controls looked too strong.
- `inconclusive_too_few_predictions`: not enough out-of-sample predictions.

A positive decision is not a trading recommendation.  It means the signal survived
the current falsification checks and deserves a stricter next test.
