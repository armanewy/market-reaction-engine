from __future__ import annotations

from pathlib import Path

from .corpus_demo import generate_corpus_demo_data
from .pipeline import default_pipeline_config, run_pipeline
from .paths import ensure_parent
import json


def generate_pipeline_demo(root: str | Path, *, seed: int = 42) -> dict[str, Path]:
    root = Path(root)
    demo = generate_corpus_demo_data(root / "seed_data", seed=seed)
    cfg = default_pipeline_config(run_id="automation_demo", domain="earnings_guidance", preset="", tickers=[])
    cfg["root"] = str(root)
    cfg["run_dir"] = str(root / "automation_run")
    cfg["source"]["mode"] = "manual_events"
    cfg["source"]["events_csv"] = str(demo["events_enriched"])
    cfg["corpus"]["require_reviewed"] = False
    cfg["prices"]["provider"] = "existing"
    cfg["prices"]["prices_dir"] = str(demo["prices_dir"])
    cfg["backtest"]["min_train"] = 30
    cfg["backtest"]["null_iterations"] = 5
    cfg["backtest"]["seed"] = seed
    cfg["gates"]["min_predictions"] = 20
    cfg["gates"]["min_trades"] = 1
    config_path = root / "automation_demo_config.json"
    ensure_parent(config_path).write_text(json.dumps(cfg, indent=2))
    report = run_pipeline(config_path)
    return {
        "config": config_path,
        "seed_events": demo["events_enriched"],
        "prices_dir": demo["prices_dir"],
        "run_dir": Path(report["run_dir"]),
        "pipeline_report": Path(report["artifacts"]["pipeline_report"]),
        "research_report": Path(report["artifacts"]["research_report_md"]),
    }
