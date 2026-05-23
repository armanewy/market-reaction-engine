# Design Notes

## Core thesis

The useful object is not “news sentiment.” The useful object is:

```text
point-in-time information set + new event + prior expectations
  -> distribution of market reaction after market/sector adjustment
```

This repository implements the measurement layer first. Prediction comes only after the event/reaction corpus is clean.

## Pipeline

```text
curated events CSV or earnings corpus
       |
       v
price loader / returns
       |
       v
expectations/context enrichment
       |
       v
event-study engine
       |
       +--> abnormal-return table
       +--> markdown report
       +--> analog retrieval
       +--> baseline model
```

## Why event study first

A naive model can learn that “good news means stock up,” which fails whenever the good news was expected. Event study gives us a target that at least tries to remove market-wide movement:

```text
stock_return = alpha + beta * benchmark_return + residual
abnormal_return = actual_return - expected_return
```

The current implementation fits alpha/beta on a pre-event estimation window and computes cumulative abnormal return over 1/3/10-day windows.

## Why no LLM predictor yet

LLMs are useful for extraction and normalization:

- identify event type
- summarize claims
- extract numeric deltas
- attach evidence spans
- estimate whether an event was expected based on point-in-time docs

But using an LLM to directly output “stock up/down” would hide leakage and make backtests difficult to trust.

## First serious real-data target

I would start with earnings events across one sector, not arbitrary news:

```text
universe: 50-200 comparable companies
period: 8-12 years
frequency: quarterly
features: surprise vs consensus, guidance, margins, prior run-up, implied move
label: next-day market-model CAR
```

That is narrow enough to debug and broad enough to have sample size.


## v0.2 earnings milestone

The first narrow corpus path is earnings/guidance-like events across comparable companies. The current implementation starts with EPS surprise because it is easy to source and test, but the design assumes EPS is only one feature. In practice, the richer expectation layer should include revenue, margins, guidance, options implied move, and point-in-time analyst revisions.

The important design constraint is that all expectation features are computed before the event-study target is measured. The code deliberately separates `enrich-expectations` from `run-event-study` so you can inspect and audit feature columns before labels are attached.
