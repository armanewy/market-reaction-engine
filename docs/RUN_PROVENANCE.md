# Run Provenance

Research outputs should be reproducible enough to identify the exact code,
configuration, and inputs that produced them. The `mre.provenance` utility
provides a small manifest layer for future pipeline integration.

Intended use:

```python
from mre.provenance import build_run_manifest, write_run_manifest

manifest = build_run_manifest(
    config=pipeline_config,
    input_paths=["data/events/reviewed_events.csv", "data/prices/SPY.csv"],
    extra={"created_at": "2026-05-25T09:00:00Z"},
)
write_run_manifest("artifacts/my_run/run_manifest.json", manifest)
```

The manifest records:

- current git SHA when available
- package version
- Python version
- deterministic config hash
- SHA-256 hashes for existing input files
- missing input paths, if any
- caller-supplied extra fields such as timestamps or provider metadata

The utility is intentionally not wired into the full pipeline yet. Future
pipeline stages should write `run_manifest.json` beside generated artifacts
once config and input paths are finalized.
