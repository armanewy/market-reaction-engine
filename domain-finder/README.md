# Domain Finder

`domain-finder` is a Rust CLI for continuously discovering and triaging event-reaction research domains before they are handed to the Market Reaction Engine (MRE) falsification harness.

It does **not** run event studies, backtests, or models. Its job is to maintain an idea funnel and answer:

> Does this domain deserve a full MRE agent, only a feasibility pass, backlog tracking, monitoring, or immediate rejection?

The current implementation includes:

- Config-driven observation ingestion from JSONL/JSON/TOML.
- Built-in source-backed candidate observation collectors.
- Candidate aggregation by domain slug.
- A 30-point domain intake score.
- Hard minimum gates for public timestamp clarity, delayed-digestion plausibility, materiality, and sample size.
- Registry-aware blocking so known failed/frozen domains do not get relaunched casually.
- Automatic intake document generation for candidates that pass the feasibility/full-lifecycle threshold.
- Continuous watch mode.

## Why this exists

MRE repeatedly found that many domains produce explanatory event reactions but fail tradability once timestamp/session, next-open execution, cost stress, feature leakage, duplicate events, and concentration are audited.

Domain Finder therefore puts the strict front-door questions **before** engineering work:

1. What is the official or primary source?
2. What is the first realistic public-awareness timestamp?
3. Why should this still be tradable after next open?
4. What hard negatives prevent lazy labels?
5. What materiality field makes the event economically meaningful?
6. What would make execution unrealistic?
7. What would make the result explanation-only rather than tradable?

## Install / build

```bash
cargo build --release
```

The binary is:

```bash
target/release/domain-finder
```

## Quick start

```bash
# Create sample config, registry, template, and observations
cargo run -- init --root . --overwrite

# Run one discovery pass
cargo run -- scan --root .

# Write built-in source-backed candidate observations
cargo run -- collect --root .

# Show machine-readable scored candidates
cargo run -- scan --root . --json

# Score one domain from a mixed feed
cargo run -- score \
  --input data/observations/sample_domains.jsonl \
  --slug bank_regulatory_enforcement

# Continuously scan every 15 minutes
cargo run -- watch --root . --interval-secs 900
```

Generated outputs:

```text
artifacts/domain_finder/domain_discovery_report.md
artifacts/domain_finder/domain_candidates.json
docs/intakes/generated/<domain>.md
data/observations/generated/<family>_observations.jsonl
```

## Observation feed format

Observation feeds are JSONL files under `data/observations/` by default. One line is one source-backed observation about a possible domain.

Example:

```json
{"slug":"bank_regulatory_enforcement","title":"Public Bank Regulatory Enforcement / Consent Orders","source_name":"OCC/FDIC/Federal Reserve","source_kind":"official_agency","official_source":true,"timestamp_quality":"clear","delayed_digest_reasons":["orders can restrict growth, capital, compliance, and operations over time"],"hard_negatives":["termination of prior order","minor procedural update","private bank"],"materiality_fields":["civil_money_penalty_pct_market_cap","capital_restriction_flag"],"mapping_notes":"public bank holding company mapping feasible","sample_size_hint":120,"liquidity_notes":"public banks tradable with liquidity filters","evidence":["official enforcement order feeds"],"tags":["bank","regulatory"]}
```

`timestamp_quality` values:

```text
clear
public_but_session_ambiguous
record_only
fuzzy
unknown
```

## Scoring

Each candidate receives 0–3 points for ten dimensions:

- official source quality
- public timestamp clarity
- delayed-digestion plausibility
- hard-negative clarity
- materiality-field clarity
- sample-size likelihood
- ticker/entity mapping feasibility
- liquidity/execution feasibility
- parser/audit feasibility
- fresh-data availability

Default total-score actions:

```text
24–30: full_lifecycle
18–23: feasibility_only
12–17: backlog
<12: skip
```

Hard minimums prevent a high aggregate score from hiding a fatal weakness:

```text
public_timestamp_clarity >= 2
delayed_digestion_plausibility >= 2
materiality_field_clarity >= 2
sample_size_likelihood >= 2
```

If a candidate fails hard minimums, it is capped at feasibility/backlog/skip.

## Registry awareness

By default the tool reads:

```text
docs/DOMAIN_RESEARCH_REGISTRY.md
```

If a domain appears as frozen/failed/mapping-insufficient/parser-not-trusted, the tool marks the candidate as `blocked_by_registry`.

If a domain appears as `underpowered_monitor`, the tool marks it `monitor_only`.

## Commands

```text
domain-finder init
domain-finder collect
domain-finder scan
domain-finder watch
domain-finder score
domain-finder make-intake
```

### `collect`

Write built-in source-backed candidate-domain observations. These are domain
ideas, not event rows or backtests.

```bash
# Write all built-in collector families
cargo run -- collect --root .

# Write one family
cargo run -- collect --root . --family fda

# Print generated observations as JSON
cargo run -- collect --root . --json
```

Built-in families:

```text
sec
agency
fda
litigation
index
```

Collector outputs are written to `data/observations/generated/` and are consumed
by `scan` because observation directory ingestion is recursive.

### `score`

Score one domain. If the input contains multiple slugs, pass `--slug` or use
`scan` for portfolio scoring.

```bash
cargo run -- score \
  --input data/observations/sample_domains.jsonl \
  --slug bank_regulatory_enforcement \
  --registry docs/DOMAIN_RESEARCH_REGISTRY.md
```

### `make-intake`

Generate a domain intake document:

```bash
cargo run -- make-intake \
  --input data/observations/sample_domains.jsonl \
  --slug bank_regulatory_enforcement \
  --registry docs/DOMAIN_RESEARCH_REGISTRY.md \
  --output docs/intakes/bank_regulatory_enforcement.md
```

`score` and `make-intake` are single-domain commands. They reject mixed-domain
inputs unless `--slug <domain>` selects exactly one domain.

## Limitations

The collectors are intentionally local-first and deterministic. They emit
source-backed candidate-domain observations with official or primary source
URLs, but they do not yet fetch live event records, build event corpora, run
MRE, or launch agents.

Recommended next milestones:

1. Add pluggable live source adapters, starting with SEC registry-aware scans.
2. Add MRE registry import/export so candidates can be merged into `DOMAIN_RESEARCH_REGISTRY.md` automatically.
3. Add persistent state and change detection so only newly improved candidates trigger reports.
4. Add scheduled Cyber Item 1.05 monitor checks.
