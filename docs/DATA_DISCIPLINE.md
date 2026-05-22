# Data Discipline

This project can easily fool you. The goal is to make it harder to fool yourself.

## Leakage traps

### Post-event articles

If an article is published after the price move, it cannot be used to predict the move. It can be used only for post-mortem explanation.

### Revised macro data

Macroeconomic series can be revised. Use the vintage available at the event time if modeling macro surprises.

### Event selection bias

Do not only label dramatic events. Include boring events and events that produced no visible stock reaction.

### Label leakage

Do not set `materiality`, `surprise_direction`, or `surprise_magnitude` after looking at the event-window return.

### Random train/test splits

Random splits leak time regimes. Use chronological or walk-forward splits.

## Minimum standard for a useful corpus

Each event should have:

- stable `event_id`
- exact `event_time`
- source URL
- source type
- event type/subtype
- release session
- point-in-time summary
- manually justified expectedness/surprise labels
- explicit uncertainty when labels are weak

## Reaction targets

Prefer short windows first:

- 1 trading day
- 3 trading days
- 10 trading days

Long windows are harder because confounding events accumulate.

## Baselines to beat

A model should beat at least:

- always predicting no abnormal move
- historical mean reaction by event type
- sector-adjusted momentum
- earnings surprise only, for earnings events
- options implied move, if available
