# Domain Finder Pipeline

Domain Finder is meant to run continuously beside Market Reaction Engine.

```text
official-source observation feeds
→ built-in source-backed candidate collectors
→ lightweight source probes
→ candidate aggregation
→ 30-point intake score
→ hard minimum gates
→ registry de-duplication / blocking
→ generated intake docs
→ top / explain / diff / alerts review
→ static dashboard
→ MRE feasibility or full lifecycle agents
```

## Continuous loop

1. Append observations to `data/observations/*.jsonl`, run `domain-finder collect`, or run a `domain-finder probe-*` command.
2. Run `domain-finder scan` or `domain-finder watch`.
3. Review `artifacts/domain_finder/domain_discovery_report.md`.
4. Use `domain-finder top`, `domain-finder explain`, and `domain-finder alerts` to focus on actionable candidates.
5. Use `domain-finder dashboard` when you need the static local research board.
6. Give generated intake docs to agents only if the gate is `full_lifecycle` or `feasibility_only`.
7. After MRE finishes a domain, update `docs/DOMAIN_RESEARCH_REGISTRY.md` so Domain Finder blocks or monitors the domain correctly.

`collect` writes deterministic source-backed candidate-domain observations to
`data/observations/generated/`. These rows are not event corpora and should not
trigger modeling by themselves.

Probe commands write source-check observations and reports to
`data/observations/probed/`. They check source URLs, add probe status metadata,
and still stop before event-corpus construction or MRE launch.

```text
domain-finder probe-sec-items
domain-finder probe-agency-actions
domain-finder probe-fda-enforcement
domain-finder probe-litigation
domain-finder probe-index-events
```

`score` and `make-intake` are single-domain commands. If the input contains
multiple slugs, pass `--slug <domain>` or use `scan` for multi-domain portfolio
scoring and intake generation.

Research-ops commands:

```text
domain-finder top --root . --limit 10
domain-finder explain --root . --slug <domain>
domain-finder diff --old <old_candidates.json> --new <new_candidates.json>
domain-finder alerts --root .
domain-finder dashboard --root . --out artifacts/domain_finder/dashboard
```

`top` and `alerts` suppress registry-blocked domains as action items. `explain`
shows the hard-minimum failures and registry history for one domain. `diff`
compares two candidate JSON snapshots and highlights newly eligible domains,
gate changes, score changes, registry changes, and revisit-trigger changes.
`dashboard` writes a static local research command center with registry status,
stop reasons, Domain Finder candidates, infrastructure entries, and per-domain
detail pages.

## Gate philosophy

The tool is conservative by design. It tries to stop domains before they consume engineering time if they lack:

- official source quality
- public timestamp clarity
- delayed-digestion plausibility
- hard negatives
- materiality fields
- sample size
- ticker/entity mapping
- execution feasibility

The strongest single gate is:

> Why should this still be tradable after next open?

Domains that only explain an immediate gap should not receive a full MRE build unless they include an intraday or pre-event thesis.
