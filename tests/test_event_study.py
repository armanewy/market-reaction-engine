from pathlib import Path

import pandas as pd

from mre.demo import generate_demo_data
from mre.event_study import run_event_study


def test_demo_event_study_runs(tmp_path: Path):
    paths = generate_demo_data(tmp_path / "demo", seed=123)
    df, diag = run_event_study(
        events_path=paths["events"],
        prices_dir=paths["prices_dir"],
        benchmark_ticker="SPY",
        horizons=(1, 3),
        estimation_window=120,
        estimation_gap=5,
        min_estimation_observations=60,
    )
    assert len(df) > 0
    assert diag.events_ok > 0
    assert "car_market_model_h1" in df.columns
    ok = df[df["event_status"] == "ok"]
    assert ok["car_market_model_h1"].notna().any()
