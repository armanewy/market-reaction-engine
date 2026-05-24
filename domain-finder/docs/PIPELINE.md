# Domain Finder Pipeline

Domain Finder is meant to run continuously beside Market Reaction Engine.

```text
official-source observation feeds
→ built-in source-backed candidate collectors
→ candidate aggregation
→ 30-point intake score
→ hard minimum gates
→ registry de-duplication / blocking
→ generated intake docs
→ MRE feasibility or full lifecycle agents
```

## Continuous loop

1. Append observations to `data/observations/*.jsonl` or run `domain-finder collect`.
2. Run `domain-finder scan` or `domain-finder watch`.
3. Review `artifacts/domain_finder/domain_discovery_report.md`.
4. Give generated intake docs to agents only if the gate is `full_lifecycle` or `feasibility_only`.
5. After MRE finishes a domain, update `docs/DOMAIN_RESEARCH_REGISTRY.md` so Domain Finder blocks or monitors the domain correctly.

`collect` writes deterministic source-backed candidate-domain observations to
`data/observations/generated/`. These rows are not event corpora and should not
trigger modeling by themselves.

`score` and `make-intake` are single-domain commands. If the input contains
multiple slugs, pass `--slug <domain>` or use `scan` for multi-domain portfolio
scoring and intake generation.

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
