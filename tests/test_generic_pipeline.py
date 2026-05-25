from __future__ import annotations

import json
from pathlib import Path

from mre.generic.pipeline import default_generic_pipeline_config, run_generic_pipeline, write_generic_pipeline_template


def test_generic_pipeline_runs_toy_official_end_to_end(tmp_path):
    config = default_generic_pipeline_config(out_dir=str(tmp_path / "out"), adapter="toy_official")
    report = run_generic_pipeline(config)
    out_dir = Path(report["out_dir"])

    assert report["status"] == "ok"
    assert report["diagnostics"]["documents"] == 2
    assert report["diagnostics"]["claims"] >= 2
    assert (out_dir / "generic_documents.csv").exists()
    assert (out_dir / "generic_events.csv").exists()
    assert (out_dir / "generic_claims.csv").exists()
    assert (out_dir / "generic_evidence_spans.csv").exists()
    assert (out_dir / "generic_claim_review_queue.csv").exists()
    assert (out_dir / "generic_quality_report.json").exists()
    assert (out_dir / "generic_quality_report.md").exists()
    assert (out_dir / "site" / "index.html").exists()
    assert (out_dir / "api" / "events.json").exists()
    assert (out_dir / "generic_digest.md").exists()
    assert (out_dir / "run_manifest.json").exists()
    assert (out_dir / "pipeline_report.json").exists()
    assert report["compatibility"][0]["readiness"]["exploration"] > 0
    json.loads((out_dir / "pipeline_report.json").read_text(encoding="utf-8"))


def test_generic_pipeline_weak_adapter_runs_with_lower_authority(tmp_path):
    config = default_generic_pipeline_config(out_dir=str(tmp_path / "weak"), adapter="toy_weak", auto_accept_min_confidence=None)
    report = run_generic_pipeline(config)
    first_summary = report["compatibility"][0]

    assert report["status"] == "ok"
    assert report["diagnostics"]["documents"] == 1
    assert "low_authority" in first_summary["known_risks"]


def test_generic_pipeline_dry_run_and_template(tmp_path):
    template = write_generic_pipeline_template(tmp_path / "generic_pipeline.json", out_dir=str(tmp_path / "out"), adapter="toy_weak")
    report = run_generic_pipeline(template, dry_run=True)

    assert template.exists()
    assert report["status"] == "dry_run"
    assert report["outputs"] == {}
    assert not (tmp_path / "out").exists()
