# M5 — richer point-in-time expectations

This milestone adds the scaffolding needed to move from an EPS-only expectations layer toward a more realistic earnings/guidance reaction corpus.

It does **not** solve access to paid point-in-time estimate, options, or analyst-revision data.  The goal is to make the project ready to accept those feeds without leaking post-event information.

## Added feed types

### 1. Exact release timestamps

File template command:

```bash
mre release-times-template --events data/events/events.csv --out data/events/release_times.csv
```

Merge command:

```bash
mre merge-release-times \
  --events data/events/events.csv \
  --release-times data/events/release_times.csv \
  --out data/events/events_exact_times.csv
```

The merge updates:

- `event_time`
- `release_session`
- `release_time_status`
- release-time source/confidence fields

This matters because daily event studies shift the first reaction day depending on whether an event was before-open, intraday, or after-close.

### 2. Rich fundamentals expectations

The expectations schema now supports:

- EPS surprise
- forward EPS guidance surprise
- revenue surprise
- forward revenue guidance surprise
- gross-margin surprise
- forward gross-margin guidance surprise
- option-implied move percentage
- analyst count

The command is unchanged:

```bash
mre expectations-template --events data/events/events_exact_times.csv --out data/events/expectations.csv
mre merge-expectations --events data/events/events_exact_times.csv --expectations data/events/expectations.csv --fill-labels --out data/events/events_with_expectations.csv
```

`merge-expectations` rejects rows whose `asof_time` is after `event_time` when leakage checks are enabled.

### 3. Option-implied move snapshots

The options template accepts rows with:

- `ticker`
- `event_id` if available
- `quote_time`
- `expiration`
- `underlying_price`
- `strike`
- `call_mid` and `put_mid`, or bid/ask pairs

Merge command:

```bash
mre merge-options \
  --events data/events/events_with_expectations.csv \
  --options data/events/options.csv \
  --out data/events/events_with_options.csv
```

The estimator selects the nearest pre-event expiration and ATM strike, then computes:

```text
implied_move_pct = (call_mid + put_mid) / underlying_price
```

This is a pragmatic expected-move proxy, not an options-pricing model.

### 4. Analyst revision history

The analyst revision feed accepts estimate rows with:

- `ticker`
- `event_id` if available
- `estimate_time`
- `analyst_id`
- `metric`: `eps`, `revenue`, `gross_margin`, `forward_revenue`, etc.
- `estimate_value`

Merge command:

```bash
mre merge-analyst-revisions \
  --events data/events/events_with_options.csv \
  --revisions data/events/analyst_revisions.csv \
  --windows 7,30 \
  --metrics eps,revenue,gross_margin,forward_revenue \
  --out data/events/events_rich_expectations.csv
```

It computes current consensus/dispersion and revision features such as:

- `analyst_eps_revision_count_7d`
- `analyst_eps_revision_mean_30d`
- `analyst_revenue_revision_pct_up_7d`
- `analyst_gross_margin_dispersion`

## Recommended chain

```bash
mre merge-release-times --events events.csv --release-times release_times.csv --out events_exact.csv
mre merge-expectations --events events_exact.csv --expectations expectations.csv --fill-labels --out events_fundamentals.csv
mre merge-options --events events_fundamentals.csv --options options.csv --out events_options.csv
mre merge-analyst-revisions --events events_options.csv --revisions analyst_revisions.csv --out events_rich.csv
mre enrich-expectations --events events_rich.csv --prices-dir data/prices --benchmark SPY --out events_rich_price_context.csv
mre run-event-study --events events_rich_price_context.csv --prices-dir data/prices --benchmark SPY --out artifacts/event_study.csv
mre walk-forward --event-study artifacts/event_study.csv --horizon 1 --min-train 40
```

## Data discipline

The important invariant remains: every feature must be knowable at or before `event_time`.

The project can validate obvious timestamp leakage, but it cannot prove a vendor file is genuinely point-in-time.  Treat feed provenance as part of the dataset, not a side detail.
