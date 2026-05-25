from pathlib import Path

import pandas as pd
import pytest

from mre.demo import generate_demo_data
from mre.event_study import EventStudyConfig, compute_event_study_frame, run_event_study


def _synthetic_event_study_inputs() -> tuple[pd.DataFrame, pd.DataFrame, EventStudyConfig]:
    index = pd.bdate_range("2024-01-02", periods=40)
    base = pd.Series(range(len(index)), index=index, dtype=float) / 10000.0
    returns = pd.DataFrame(
        {
            "ABC": base + 0.001,
            "SPY": base,
            "XLV": base + 0.0005,
        },
        index=index,
    )
    events = pd.DataFrame(
        [
            {
                "event_id": "e1",
                "ticker": "abc",
                "event_time": index[25],
                "release_session": "intraday",
                "sector_benchmark": "xlv",
            }
        ]
    )
    config = EventStudyConfig(
        benchmark_ticker="SPY",
        horizons=(1,),
        estimation_window=15,
        estimation_gap=2,
        min_estimation_observations=10,
    )
    return events, returns, config


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


def test_compute_event_study_normalizes_lowercase_return_columns_for_benchmark():
    events, returns, config = _synthetic_event_study_inputs()
    lowercase_returns = returns[["ABC", "SPY"]].rename(columns={"ABC": "abc", "SPY": "spy"})

    df, diag = compute_event_study_frame(events, lowercase_returns, config)

    assert diag.events_ok == 1
    assert df.loc[0, "event_status"] == "ok"
    assert df.loc[0, "benchmark_ticker"] == "SPY"
    assert pd.notna(df.loc[0, "car_market_model_h1"])


def test_compute_event_study_missing_benchmark_still_raises_clear_value_error():
    events, returns, config = _synthetic_event_study_inputs()
    missing_benchmark_returns = returns[["ABC", "XLV"]].rename(columns={"ABC": "abc", "XLV": "xlv"})

    with pytest.raises(ValueError, match="Benchmark ticker SPY not found in returns data"):
        compute_event_study_frame(events, missing_benchmark_returns, config)


def test_compute_event_study_normalized_ticker_columns_match_uppercase_inputs():
    events, returns, config = _synthetic_event_study_inputs()
    lowercase_returns = returns.rename(columns=str.lower)

    uppercase_df, uppercase_diag = compute_event_study_frame(events, returns, config)
    lowercase_df, lowercase_diag = compute_event_study_frame(events, lowercase_returns, config)

    assert uppercase_diag.events_ok == 1
    assert lowercase_diag.events_ok == 1
    assert lowercase_df.loc[0, "sector_return_h1"] == pytest.approx(uppercase_df.loc[0, "sector_return_h1"])
    assert lowercase_df.loc[0, "car_sector_adj_h1"] == pytest.approx(uppercase_df.loc[0, "car_sector_adj_h1"])
    assert lowercase_df.loc[0, "car_market_model_h1"] == pytest.approx(uppercase_df.loc[0, "car_market_model_h1"])
    assert lowercase_df.loc[0, "benchmark_ticker"] == uppercase_df.loc[0, "benchmark_ticker"]
