from pathlib import Path

from mre.demo import generate_demo_data
from mre.event_study import run_event_study
from mre.modeling import find_analogs, train_direction_model


def test_train_and_analogs_run(tmp_path: Path):
    paths = generate_demo_data(tmp_path / "demo", seed=123)
    df, _ = run_event_study(
        events_path=paths["events"],
        prices_dir=paths["prices_dir"],
        benchmark_ticker="SPY",
        horizons=(1,),
        estimation_window=120,
        estimation_gap=5,
        min_estimation_observations=60,
    )
    event_study_path = tmp_path / "event_study.csv"
    df.to_csv(event_study_path, index=False)
    report = train_direction_model(
        event_study_path,
        horizon=1,
        out_model=tmp_path / "model.joblib",
        out_report=tmp_path / "model_report.json",
    )
    assert report["n_events"] > 10
    ok = df[df["event_status"] == "ok"]
    analogs = find_analogs(event_study_path, ok.iloc[0]["event_id"], k=3, horizon=1)
    assert len(analogs) == 3
    assert "similarity" in analogs.columns
