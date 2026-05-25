from pathlib import Path

import pandas as pd

from mre.demo import generate_demo_data
from mre.event_study import run_event_study
from mre.features import FeatureSpec
from mre.modeling import available_features, find_analogs, issuer_grouped_diagnostics, make_direction_pipeline, train_direction_model, walk_forward_direction_model


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


def test_available_features_default_behavior_unchanged():
    frame = pd.DataFrame({"ticker": ["AAA"], "event_type": ["earnings"], "materiality": [0.8], "all_null_numeric": [None]})

    categorical, numeric = available_features(frame)

    assert categorical == ["ticker", "event_type"]
    assert numeric == ["materiality"]


def test_train_direction_model_accepts_custom_feature_specs(tmp_path: Path):
    paths = generate_demo_data(tmp_path / "demo_specs", seed=321)
    df, _ = run_event_study(
        events_path=paths["events"],
        prices_dir=paths["prices_dir"],
        benchmark_ticker="SPY",
        horizons=(1,),
        estimation_window=120,
        estimation_gap=5,
        min_estimation_observations=60,
    )
    event_study_path = tmp_path / "event_study_specs.csv"
    df.to_csv(event_study_path, index=False)
    specs = [
        FeatureSpec("event_type", "categorical", "event_metadata"),
        FeatureSpec("materiality", "numeric", "manual_review"),
        FeatureSpec("raw_return_h1", "numeric", "derived", leakage_risk="high"),
    ]

    report = train_direction_model(event_study_path, horizon=1, feature_specs=specs)

    assert report["feature_spec_mode"] == "custom"
    assert report["categorical_features"] == ["event_type"]
    assert report["numeric_features"] == ["materiality"]
    assert "raw_return_h1" not in report["numeric_features"]


def test_issuer_grouped_diagnostics_multiple_tickers():
    frame = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA", "BBB", "BBB", "CCC", "CCC"],
            "event_type": ["earnings"] * 6,
            "materiality": [0.1, 0.8, 0.2, 0.7, 0.3, 0.9],
        }
    )
    y = pd.Series([0, 1, 0, 1, 0, 1])

    report = issuer_grouped_diagnostics(frame, y, make_direction_pipeline, min_train=4)

    assert report["n_unique_tickers"] == 3
    assert len(report["per_ticker"]) == 3
    assert all(row["status"] == "ok" for row in report["leave_one_ticker_out"])


def test_issuer_grouped_diagnostics_one_ticker_warns():
    frame = pd.DataFrame({"ticker": ["AAA", "AAA"], "event_type": ["earnings", "earnings"], "materiality": [0.1, 0.8]})
    y = pd.Series([0, 1])

    report = issuer_grouped_diagnostics(frame, y, make_direction_pipeline, min_train=2)

    assert report["n_unique_tickers"] == 1
    assert report["leave_one_ticker_out"] == []
    assert any("one ticker" in warning.lower() for warning in report["warnings"])


def test_issuer_grouped_diagnostics_skips_one_class_train_and_insufficient_data():
    frame = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA", "BBB", "CCC"],
            "event_type": ["earnings"] * 4,
            "materiality": [0.1, 0.2, 0.3, 0.4],
        }
    )
    y = pd.Series([1, 1, 1, 0])

    insufficient = issuer_grouped_diagnostics(frame, y, make_direction_pipeline, min_train=10)
    one_class = issuer_grouped_diagnostics(frame, y, make_direction_pipeline, min_train=2)

    assert {row["status"] for row in insufficient["leave_one_ticker_out"]} == {"skipped_insufficient_train_rows"}
    assert "skipped_one_class_train" in {row["status"] for row in one_class["leave_one_ticker_out"]}


def test_walk_forward_issuer_diagnostics_are_opt_in(tmp_path: Path):
    paths = generate_demo_data(tmp_path / "demo_issuer", seed=456)
    df, _ = run_event_study(
        events_path=paths["events"],
        prices_dir=paths["prices_dir"],
        benchmark_ticker="SPY",
        horizons=(1,),
        estimation_window=120,
        estimation_gap=5,
        min_estimation_observations=60,
    )
    event_study_path = tmp_path / "event_study_issuer.csv"
    df.to_csv(event_study_path, index=False)

    default_report = walk_forward_direction_model(event_study_path, horizon=1, min_train=10)
    diagnostic_report = walk_forward_direction_model(event_study_path, horizon=1, min_train=10, include_issuer_diagnostics=True, issuer_diagnostics_min_train=10)

    assert "issuer_grouped_diagnostics" not in default_report
    assert "issuer_grouped_diagnostics" in diagnostic_report
