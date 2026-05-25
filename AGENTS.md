# Market Reaction Engine Agent Guide

Market Reaction Engine is a research and falsification workbench, not a trading
signal product. Do not claim tradable alpha, live candidates, or production
readiness unless promotion gates, falsification checks, fresh confirmation, and
execution realism explicitly pass.

Core engineering norms:

- Preserve point-in-time discipline. Features, labels, parser decisions, and
  review metadata must be known at or before `event_time`.
- Treat timestamp/session handling as high risk. Unknown release sessions are
  explanatory-only until audited.
- Treat feature leakage as high risk. Do not add post-event returns, model
  outputs, or outcome-derived fields to modeling features.
- Treat parser positives as candidates. Require evidence spans, source document
  IDs, review status, label quality, duplicate checks, and timestamp audit before
  modeling.
- Keep changes narrowly scoped. Do not rewrite unrelated domains while fixing a
  core bug or adding one scaffold.
- Add or update tests for behavior changes. Use small deterministic fixtures and
  avoid network-dependent tests.
- Avoid new runtime dependencies unless the benefit is clear and documented.

Useful commands:

```bash
python -m pytest
python -m pytest tests/test_event_study.py
python -m pytest tests/test_pipeline_automation.py
python -m pytest tests/test_backtest_harness.py
python -m ruff check .
```

Generated artifacts:

- Keep durable examples and tiny fixtures under `data/`, `examples/`, or
  `tests/fixtures/` when they are intentionally committed.
- Keep generated run outputs under `runs/`, `research/`, or ignored `artifacts/`
  paths.
- Do not commit large generated price files, backtest outputs, model binaries,
  or ad hoc research runs.
