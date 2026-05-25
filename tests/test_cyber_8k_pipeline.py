from __future__ import annotations

import json
from pathlib import Path

from mre.cyber_8k_pipeline import default_cyber_8k_config, run_cyber_8k_pipeline, write_cyber_8k_pipeline_template


FIXTURE = "tests/fixtures/cyber_8k/source_documents.csv"


def test_cyber_8k_pipeline_runs_offline_from_existing_manifest(tmp_path):
    config = default_cyber_8k_config(source_documents_csv=FIXTURE, out_dir=str(tmp_path / "out"))
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    report = run_cyber_8k_pipeline(config_path)

    out_dir = tmp_path / "out"
    assert Path(report["outputs"]["pipeline_report"]).exists()
    assert (out_dir / "cyber_events.csv").exists()
    assert (out_dir / "cyber_claims.csv").exists()
    assert (out_dir / "cyber_claim_review_queue.csv").exists()
    assert (out_dir / "api" / "events.json").exists()
    assert (out_dir / "site" / "index.html").exists()
    assert (out_dir / "cyber_8k_digest.md").exists()
    assert (out_dir / "run_manifest.json").exists()
    assert [stage["name"] for stage in report["stages"]][-1] == "run_manifest"


def test_cyber_8k_pipeline_dry_run_does_not_write_outputs(tmp_path):
    config = default_cyber_8k_config(source_documents_csv=FIXTURE, out_dir=str(tmp_path / "out"))

    report = run_cyber_8k_pipeline(config, dry_run=True)

    assert report["status"] == "dry_run"
    assert not (tmp_path / "out").exists()
    assert {stage["status"] for stage in report["stages"]} == {"planned"}


def test_write_cyber_8k_pipeline_template(tmp_path):
    out = write_cyber_8k_pipeline_template(tmp_path / "template.json", source_documents_csv=FIXTURE, out_dir=str(tmp_path / "out"))

    data = json.loads(out.read_text(encoding="utf-8"))

    assert data["source"]["mode"] == "existing_manifest"
    assert data["source"]["source_documents_csv"] == FIXTURE
