# Domain Lifecycle

The project advances domains through explicit evidence and falsification states.
Most domains should stop before modeling; a polished "no signal" result is a
successful outcome when the evidence does not support promotion.

## Artifact States

```text
candidate_source_rows
  -> parser_review_queue
  -> source_grounded_events
  -> timestamp_audited_events
  -> model_ready_corpus
  -> falsification_result
  -> fresh_confirmation_result
  -> candidate_paper_signal
```

Domains can also end as `frozen`, `failed`, `monitor`, `parser not trusted`,
`mapping insufficient`, `timestamp insufficient`, or `execution unrealistic`.
See `docs/DOMAIN_RESEARCH_REGISTRY.md` for current statuses.

## Transition Gates

`candidate_source_rows` to `parser_review_queue` requires official or
traceable sources, stable document IDs, source URLs, and deterministic parser
candidate output.

`parser_review_queue` to `source_grounded_events` requires review status,
evidence text or source document IDs, label quality, and parser false-positive
audit results.

`source_grounded_events` to `timestamp_audited_events` requires known
`release_session`, timestamp audit status, duplicate-event checks, and a
documented first realistic entry policy.

`timestamp_audited_events` to `model_ready_corpus` requires promotion gates:
minimum reviewed rows, minimum model-eligible rows, likely walk-forward
predictions, evidence coverage, known sessions, duplicate clearance, timestamp
audit clearance, and execution survivability classification.

`model_ready_corpus` to `falsification_result` requires event study,
walk-forward validation, calibration, cost/slippage simulation, null shuffle,
placebo controls, peer controls, and concentration diagnostics.

`falsification_result` to `fresh_confirmation_result` requires a held-out or
new-period check using the same rules and thresholds selected without looking at
the final out-of-sample rows.

`fresh_confirmation_result` to `candidate_paper_signal` requires a stable,
auditable result that survives costs, execution timing, controls, issuer
concentration checks, and multiple-hypothesis context. This is still not a live
tradable signal.

## Common Failure Modes

- Timestamp/session leakage
- Feature lookahead
- Duplicate-event leakage
- Parser false positives
- Unreviewed labels
- Missing source evidence
- Unmapped or weakly mapped issuers
- Next-open execution failure
- Cost/slippage fragility
- Issuer or sector concentration
- Underpowered samples
- Failed fresh confirmation
