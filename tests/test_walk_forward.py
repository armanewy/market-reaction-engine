from pathlib import Path

from mre.earnings_demo import generate_earnings_demo_data
from mre.event_study import run_event_study
from mre.modeling import walk_forward_direction_model


def test_earnings_demo_walk_forward_runs(tmp_path: Path):
    paths = generate_earnings_demo_data(tmp_path / "earnings_demo", seed=11)
    event_study, diag = run_event_study(
        paths["events_enriched"],
        paths["prices_dir"],
        benchmark_ticker="SPY",
        horizons=(1,),
        estimation_window=80,
        estimation_gap=5,
        min_estimation_observations=40,
    )
    assert diag.events_ok > 20
    event_study_path = tmp_path / "event_study.csv"
    event_study.to_csv(event_study_path, index=False)
    report = walk_forward_direction_model(
        event_study_path,
        horizon=1,
        min_train=20,
        out_predictions=tmp_path / "preds.csv",
        out_report=tmp_path / "report.json",
    )
    assert report["n_predictions"] > 0
    assert "metrics" in report
