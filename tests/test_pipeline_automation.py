from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from mre.corpus_demo import generate_corpus_demo_data
from mre.pipeline import default_pipeline_config, run_pipeline, write_pipeline_template
from mre.review import make_review_queue


def test_pipeline_template_roundtrip(tmp_path: Path):
    out = tmp_path / "pipeline.json"
    cfg = write_pipeline_template(out, run_id="test_run", domain="earnings_guidance", preset="semiconductors", source_mode="manual_events")
    loaded = json.loads(out.read_text())
    assert loaded["run_id"] == "test_run"
    assert loaded["domain"] == "earnings_guidance"
    assert loaded["source"]["mode"] == "manual_events"
    assert cfg["schema_version"] == loaded["schema_version"]


def test_review_queue_uses_fact_evidence(tmp_path: Path):
    events = tmp_path / "events.csv"
    facts = tmp_path / "facts.csv"
    out = tmp_path / "review_queue.csv"
    pd.DataFrame([
        {
            "event_id": "e1",
            "ticker": "ABC",
            "event_time": "2024-01-02T16:05:00",
            "event_type": "earnings",
            "summary": "ABC reports results.",
            "release_session": "after_close",
            "materiality": 0.8,
        }
    ]).to_csv(events, index=False)
    pd.DataFrame([
        {
            "event_id": "e1",
            "fact_name": "actual_eps",
            "value": 1.23,
            "confidence": 0.95,
            "evidence_text": "ABC reported EPS of $1.23.",
        }
    ]).to_csv(facts, index=False)
    queue, diag = make_review_queue(events, out, facts_path=facts, auto_accept_min_confidence=0.9)
    assert diag.rows_with_evidence == 1
    assert queue.iloc[0]["evidence_status"] == "has_evidence"
    assert queue.iloc[0]["review_status"] == "reviewed"


def test_run_pipeline_with_existing_prices(tmp_path: Path):
    seed = generate_corpus_demo_data(tmp_path / "seed", seed=1)
    cfg = default_pipeline_config(run_id="automation_test", domain="earnings_guidance", preset="", tickers=[])
    cfg["root"] = str(tmp_path)
    cfg["run_dir"] = str(tmp_path / "run")
    cfg["source"]["mode"] = "manual_events"
    cfg["source"]["events_csv"] = str(seed["events_enriched"])
    cfg["corpus"]["require_reviewed"] = False
    cfg["prices"]["provider"] = "existing"
    cfg["prices"]["prices_dir"] = str(seed["prices_dir"])
    cfg["controls"]["make_placebo"] = False
    cfg["controls"]["make_peer_controls"] = False
    cfg["backtest"]["min_train"] = 30
    cfg["backtest"]["null_iterations"] = 1
    cfg["gates"]["min_predictions"] = 20
    cfg["gates"]["min_trades"] = 1
    path = tmp_path / "pipeline.json"
    path.write_text(json.dumps(cfg, indent=2))
    report = run_pipeline(path)
    assert report["artifacts"]["pipeline_report"]
    assert Path(report["artifacts"]["research_report_md"]).exists()
    assert "decision" in report["decision"]
    assert any(step["name"] == "event_study_main" and step["status"] == "ok" for step in report["steps"])
