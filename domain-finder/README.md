# Domain Finder

`domain-finder` is a Rust CLI for continuously discovering and triaging event-reaction research domains before they are handed to the Market Reaction Engine (MRE) falsification harness.

It does **not** run event studies, backtests, or models. Its job is to maintain an idea funnel and answer:

> Does this domain deserve a full MRE agent, only a feasibility pass, backlog tracking, monitoring, or immediate rejection?

The current implementation includes:

- Config-driven observation ingestion from JSONL/JSON/TOML.
- Built-in source-backed candidate observation collectors.
- Lightweight source probes that annotate observations with source-check metadata.
- Candidate aggregation by domain slug.
- A 30-point domain intake score.
- Hard minimum gates for public timestamp clarity, delayed-digestion plausibility, materiality, and sample size.
- Registry-aware blocking so known failed/frozen domains do not get relaunched casually.
- Automatic intake document generation for candidates that pass the feasibility/full-lifecycle threshold.
- Research-ops views for top candidates, per-domain explanations, scan diffs, and alerts.
- Static local research dashboard generation.
- Conservative orchestration for discovery, intake generation, job queueing, approval, and prompt generation.
- Deterministic automated job review with auditable approve/reject artifacts.
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

# Probe official/primary sources and write dynamic observations
cargo run -- probe-sec-items --root .
cargo run -- probe-fda-enforcement --root .
cargo run -- probe-agency-actions --root .

# Show machine-readable scored candidates
cargo run -- scan --root . --json

# Show the highest-priority non-blocked candidates
cargo run -- top --root . --limit 10

# Explain one domain's score, gate, warnings, and registry status
cargo run -- explain --root . --slug cybersecurity_material_incidents_8k

# Build a static local research dashboard
cargo run -- dashboard --root . --out artifacts/domain_finder/dashboard

# Queue eligible domains for human approval without launching agents
cargo run -- orchestrate --root . --once

# Run the policy-controlled hands-off loop in safe mode
cargo run -- orchestrate --root . --once --auto

# Deterministically review queued jobs without relying on chat/Codex judgment
cargo run -- review-jobs --root .

# Review jobs and generate prompts for any candidates that pass policy
cargo run -- review-jobs --root . --run-approved

# Approve exactly one queued job and generate its research prompt
cargo run -- approve --root . --domain material_customer_contract_loss_8k
cargo run -- research-prompt --root . --domain material_customer_contract_loss_8k

# Run approved jobs through the configured runner adapter
cargo run -- run-approved --root .

# Mark a completed run and append feedback for future scoring
cargo run -- complete-job \
  --root . \
  --domain material_customer_contract_loss_8k \
  --status parser_not_trusted \
  --report ../artifacts/material_customer_contract_loss_8k_domain_final_report.md \
  --registry-update ../artifacts/material_customer_contract_loss_8k_registry_update.json

# Reject or archive queued jobs you do not want active
cargo run -- reject --root . --domain executive_departure_for_cause_8k --reason "not first priority"
cargo run -- archive-job --root . --domain regulatory_investigation_8k --reason "deferred"

# Inspect job history and write a local digest
cargo run -- job-history --root .
cargo run -- notification-digest --root .

# Run the full unattended local loop once
powershell -ExecutionPolicy Bypass -File scripts/run_orchestrator_loop.ps1

# Register the unattended loop in Windows Task Scheduler
powershell -ExecutionPolicy Bypass -File scripts/install_task_scheduler.ps1 -IntervalMinutes 60

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
data/observations/probed/<family>_probe_observations.jsonl
artifacts/domain_finder/dashboard/index.html
artifacts/domain_finder/dashboard/dashboard_state.json
artifacts/orchestrator/jobs/<domain>.json
artifacts/orchestrator/reviews/<domain>.json
artifacts/orchestrator/notifications/latest.md
artifacts/orchestrator/notifications/good_news.md
artifacts/orchestrator/prompts/<domain>.md
artifacts/orchestrator/domain_feedback.jsonl
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
domain-finder probe-sec-items
domain-finder probe-agency-actions
domain-finder probe-fda-enforcement
domain-finder probe-litigation
domain-finder probe-index-events
domain-finder scan
domain-finder watch
domain-finder top
domain-finder explain
domain-finder diff
domain-finder alerts
domain-finder dashboard
domain-finder orchestrate
domain-finder approve
domain-finder reject
domain-finder archive-job
domain-finder complete-job
domain-finder run-approved
domain-finder review-jobs
domain-finder list-jobs
domain-finder job-history
domain-finder notification-digest
domain-finder research-prompt
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

## Fully Automated Local Review

`review-jobs` is the durable, Task Scheduler-friendly review step. It does not
ask an LLM or a human to approve queued work. It applies the local
`[review]` policy from `config/orchestrator.toml` and writes one audit record per
decision:

```text
artifacts/orchestrator/reviews/<domain>.json
```

The review policy is intentionally stricter than the intake score. A queued job
is rejected or deferred if it is registry-blocked, monitor-only, backed only by
static/offline observations, missing live source-probe evidence, below hard
front-door minimums, or affected by prior low true-positive-yield feedback.

A local unattended cycle can be run from Windows Task Scheduler as:

```powershell
cd C:\Users\aoztu\Documents\market-reaction-engine-domain-integration\domain-finder
cargo run -- orchestrate --root . --once --auto
cargo run -- review-jobs --root . --run-approved
cargo run -- dashboard --root . --out artifacts/domain_finder/dashboard
```

The checked-in runner script wraps that sequence and logs each execution:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_orchestrator_loop.ps1
```

To register it as a durable local scheduled task:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_task_scheduler.ps1 -IntervalMinutes 60
```

The installer refuses intervals below 15 minutes. More frequent polling usually
does not cast a wider research net; better source probes and observation feeds do.

This automates routine approval/rejection and prompt generation while keeping
positive-survival claims gated. Safe terminal failures can be handled by
`complete-job`; candidate paper signals should still be notification-only unless
you explicitly change registry-update policy.

Good-news events are separated from routine digests:

```text
artifacts/orchestrator/notifications/good_news.md
```

That file is intended for prompt-ready jobs, positive-survival statuses, and
operational issues such as stale or failed runners. Routine parser/mapping/
underpowered failures stay in the normal digest and dashboard.

### Probe commands

Probe commands start from the built-in observations, check the configured
official/primary source URLs, and write dynamic observations plus a source probe
report. They still do not build event corpora, run MRE, or launch agents.

```bash
cargo run -- probe-sec-items --root .
cargo run -- probe-agency-actions --root .
cargo run -- probe-fda-enforcement --root .
cargo run -- probe-litigation --root .
cargo run -- probe-index-events --root .
```

Common options:

```bash
# Write probe observations without fetching source URLs
cargo run -- probe-sec-items --root . --offline

# Write to a custom directory
cargo run -- probe-fda-enforcement --root . --output-dir data/observations/probed

# Print probed observations as JSON
cargo run -- probe-agency-actions --root . --json
```

Probe outputs are written to:

```text
data/observations/probed/<family>_probe_observations.jsonl
data/observations/probed/<family>_source_probe_report.md
```

The emitted observations include `source_probe`, `probe:<family>`, and
`probe_status:<status>` tags, plus evidence lines with HTTP status, byte count,
and keyword-hit metadata when fetched.

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

### `top`

Show the highest-priority current candidates from a fresh scan. Registry-blocked
and skipped domains are suppressed by default.

```bash
cargo run -- top --root . --limit 10
cargo run -- top --root . --limit 10 --json
```

### `explain`

Explain one domain's scorecard, registry state, hard-minimum failures, warnings,
and recommended next action.

```bash
cargo run -- explain --root . --slug cybersecurity_material_incidents_8k
cargo run -- explain --root . --slug cybersecurity_material_incidents_8k --json
```

### `diff`

Compare two scan JSON files and report new domains, score changes, gate changes,
registry changes, revisit-trigger changes, and newly intake-eligible domains.

```bash
cargo run -- diff \
  --old artifacts/domain_finder/previous_candidates.json \
  --new artifacts/domain_finder/domain_candidates.json
```

### `alerts`

Emit current actionable alerts from a fresh scan. Frozen or failed registry
domains are counted as suppressed, not surfaced as action items.

```bash
cargo run -- alerts --root .
cargo run -- alerts --root . --json
```

### `dashboard`

Build a local static research dashboard. The dashboard is a read-only research
command center, not a trading dashboard. It reads the canonical registry, latest
Domain Finder candidates when available, and local report artifacts, then writes
HTML, CSS, per-domain detail pages, and normalized JSON state.

```bash
cargo run -- dashboard --root . --out artifacts/domain_finder/dashboard
```

When run from the `domain-finder` directory, the command prefers
`../docs/DOMAIN_RESEARCH_REGISTRY.md` if it exists, so it uses the canonical MRE
registry instead of the sample local registry. You can override that explicitly:

```bash
cargo run -- dashboard \
  --root . \
  --registry ../docs/DOMAIN_RESEARCH_REGISTRY.md \
  --out artifacts/domain_finder/dashboard
```

Dashboard outputs:

```text
artifacts/domain_finder/dashboard/index.html
artifacts/domain_finder/dashboard/dashboard_state.json
artifacts/domain_finder/dashboard/assets/style.css
artifacts/domain_finder/dashboard/domains/<domain>.html
```

### Orchestration

The orchestrator automates the discovery-to-approval queue and can optionally
run a configured research runner. It is intentionally conservative:

```text
collect/probe/scan
-> generate MRE-root intake docs
-> queue eligible jobs
-> write local Markdown notification
-> wait for human approval
-> generate a research prompt
-> optionally launch the configured runner
-> ingest final report / registry-update artifacts
-> auto-apply only safe terminal registry statuses when enabled
```

By default it does **not** launch Codex agents, update the registry, graduate
signals, or make trading claims. Those behaviors are policy/config controlled.
`candidate_paper_signal` is never auto-applied unless explicitly enabled.

```bash
# Run one orchestration pass
cargo run -- orchestrate --root . --once

# Run one policy-controlled auto pass
cargo run -- orchestrate --root . --once --auto

# Run continuously every 15 minutes
cargo run -- orchestrate --root . --watch --interval-secs 900

# Run continuously with the safe-mode policy enabled
cargo run -- orchestrate --root . --watch --interval-secs 900 --auto

# Test the loop without live source fetching
cargo run -- orchestrate --root . --once --offline-probes

# Inspect queued work
cargo run -- list-jobs --root .

# Approve one job after intake review
cargo run -- approve --root . --domain material_customer_contract_loss_8k

# Reject or archive queued work that should not stay active
cargo run -- reject --root . --domain executive_departure_for_cause_8k --reason "not first priority"
cargo run -- archive-job --root . --domain regulatory_investigation_8k --reason "deferred"

# Generate the MRE research prompt for an approved job
cargo run -- research-prompt --root . --domain material_customer_contract_loss_8k

# Generate prompts and optionally launch configured runners for approved jobs
cargo run -- run-approved --root .

# Mark a completed MRE run and append feedback
cargo run -- complete-job \
  --root . \
  --domain material_customer_contract_loss_8k \
  --status parser_not_trusted \
  --report ../artifacts/material_customer_contract_loss_8k_domain_final_report.md \
  --registry-update ../artifacts/material_customer_contract_loss_8k_registry_update.json \
  --source-rows 191 \
  --parsed-rows 191 \
  --machine-positive-rows 1 \
  --audited-true-positive-rows 0 \
  --reviewed-usable-rows 0 \
  --likely-oos 0

# Inspect history snapshots and write the digest
cargo run -- job-history --root .
cargo run -- notification-digest --root .
```

The default config is `config/orchestrator.toml`. By default, the orchestrator
queues at most three new jobs only when there are no active non-archived jobs.
This prevents repeated watch runs from accumulating a large backlog while a
human review is still pending.

Safe-mode settings live in:

```toml
[approval]
auto_approve = false
max_new_jobs_per_run = 1
max_active_jobs = 1

[runner]
mode = "manual" # manual, noop, or command

[registry_updates]
auto_apply_safe_terminal_statuses = false
auto_apply_candidate_paper_signal = false
```

Routine failures are logged to the digest and feedback file. Positive or
human-review statuses such as `promising_requires_fresh_confirmation`,
`fresh_confirmed_pending_audit`, and `candidate_paper_signal` are notification
events.

Orchestrator outputs:

```text
artifacts/orchestrator/jobs/<domain>.json
artifacts/orchestrator/notifications/latest.md
artifacts/orchestrator/notifications/digest.md
artifacts/orchestrator/history/<timestamp>_jobs.json
artifacts/orchestrator/prompts/<domain>.md
artifacts/orchestrator/domain_feedback.jsonl
../docs/intakes/generated/<domain>.md
```

## Limitations

The collectors, probes, and orchestrator are intentionally bounded. They emit
source-backed candidate-domain observations, source-check metadata, intake
docs, queued jobs, research prompts, and optional runner invocations. They do
not fetch full live event records, build event corpora, graduate signals, or
make trading claims.

Recommended next milestones:

1. Add persistent scan snapshots so `diff` and `alerts` can compare against the last run automatically.
2. Add pluggable live source adapters, starting with SEC registry-aware scans.
3. Add scheduled Cyber Item 1.05 monitor checks.
4. Add richer runner adapters once the command-mode flow has been exercised.
