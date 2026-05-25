from __future__ import annotations

import numpy as np
import pandas as pd

from mre.backtest import (
    apply_nested_expanding_thresholds,
    calibration_table,
    concentration_diagnostics,
    make_peer_control_events,
    make_placebo_events,
    null_shuffle_strategy_test,
    run_research_backtest,
    simulate_event_strategy,
)


def test_calibration_strategy_and_null_shuffle(tmp_path):
    preds = pd.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(12)],
            "predicted_positive_probability": [0.8, 0.7, 0.2, 0.3, 0.6, 0.4, 0.9, 0.1, 0.55, 0.45, 0.65, 0.35],
            "y_true": [1, 1, 0, 0, 1, 0, 1, 0, 1, 0, 1, 0],
            "car_market_model_h1": [0.03, 0.02, -0.02, -0.01, 0.01, -0.01, 0.04, -0.03, 0.005, -0.004, 0.015, -0.012],
        }
    )
    cal, report = calibration_table(preds, bins=5)
    assert report["n_predictions"] == 12
    assert len(cal) == 5
    trades, strategy = simulate_event_strategy(preds, long_threshold=0.6, allow_short=True, cost_bps=1, slippage_bps=1)
    assert strategy["n_trades"] > 0
    assert {1, -1}.issubset(set(trades["position"]))
    null, null_report = null_shuffle_strategy_test(preds, n_iter=10, seed=1, long_threshold=0.6, allow_short=True)
    assert len(null) == 10
    assert "one_sided_p_value_actual_ge_null" in null_report


def test_nested_expanding_thresholds_use_only_prior_rows():
    preds = pd.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(6)],
            "predicted_positive_probability": [0.56, 0.57, 0.58, 0.80, 0.81, 0.82],
            "y_true": [1, 1, 1, 1, 1, 1],
            "car_market_model_h1": [0.03, 0.03, 0.03, -0.02, -0.02, -0.02],
        }
    )

    selected, report = apply_nested_expanding_thresholds(
        preds,
        candidate_thresholds=[0.55, 0.75],
        default_threshold=0.60,
        min_threshold_selection_rows=3,
    )

    assert list(selected["selected_long_threshold"].iloc[:3]) == [0.60, 0.60, 0.60]
    assert selected.loc[3, "selected_long_threshold"] == 0.55
    assert selected.loc[3, "threshold_selection_prior_rows"] == 3
    assert report["rows_using_default_threshold"] == 3


def test_concentration_diagnostics_empty_trades():
    report = concentration_diagnostics(pd.DataFrame(columns=["ticker", "event_type", "net_event_return"]))

    assert report["n_rows"] == 0
    assert report["per_ticker"] == []
    assert report["warnings"]


def test_concentration_diagnostics_one_ticker_warns():
    trades = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA"],
            "event_type": ["earnings", "earnings"],
            "net_event_return": [0.02, -0.01],
        }
    )

    report = concentration_diagnostics(trades)

    assert report["n_unique_tickers"] == 1
    assert report["top_1_ticker_share_by_abs_return"] == 1.0
    assert any("one ticker" in warning for warning in report["warnings"])


def test_concentration_diagnostics_many_tickers_and_dominant_ticker():
    balanced = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB", "CCC", "DDD", "EEE"],
            "event_type": ["earnings"] * 5,
            "net_event_return": [0.01, -0.01, 0.01, -0.01, 0.01],
        }
    )
    dominant = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA", "BBB", "CCC", "DDD", "EEE"],
            "event_type": ["earnings"] * 6,
            "net_event_return": [0.50, -0.30, 0.01, 0.01, -0.01, 0.01],
        }
    )

    balanced_report = concentration_diagnostics(balanced)
    dominant_report = concentration_diagnostics(dominant)

    assert balanced_report["n_unique_tickers"] == 5
    assert abs(balanced_report["top_1_ticker_share_by_abs_return"] - 0.2) < 1e-9
    assert dominant_report["top_1_ticker_share_by_abs_return"] > 0.9
    assert any("75%" in warning for warning in dominant_report["warnings"])


def _write_price(path, ticker):
    dates = pd.bdate_range("2020-01-01", "2021-12-31")
    adj = 100 * np.exp(np.cumsum(np.full(len(dates), 0.001)))
    df = pd.DataFrame({"date": dates, "open": adj, "high": adj, "low": adj, "close": adj, "adj_close": adj, "volume": 1000})
    df.to_csv(path / f"{ticker}.csv", index=False)


def test_placebo_and_peer_controls(tmp_path):
    events = pd.DataFrame(
        {
            "event_id": ["e1", "e2"],
            "ticker": ["AAA", "BBB"],
            "event_time": ["2020-06-01T16:05:00", "2020-07-01T08:30:00"],
            "event_type": ["earnings", "recall"],
            "event_subtype": ["quarterly_results", "safety_recall"],
            "event_family": ["earnings_guidance", "recall_safety"],
            "summary": ["A", "B"],
            "release_session": ["after_close", "before_open"],
        }
    )
    events_path = tmp_path / "events.csv"
    events.to_csv(events_path, index=False)
    prices = tmp_path / "prices"
    prices.mkdir()
    _write_price(prices, "AAA")
    _write_price(prices, "BBB")
    placebo, diag = make_placebo_events(events_path, prices, tmp_path / "placebo.csv", n_per_event=2, seed=3)
    assert len(placebo) == 4
    assert diag.rows_used == 4
    assert set(placebo["event_type"]) == {"placebo"}
    peer, peer_diag = make_peer_control_events(events_path, tmp_path / "peer.csv")
    assert len(peer) == 2
    assert peer_diag.rows_used == 2
    assert set(peer["event_type"]) == {"peer_control"}


def test_research_backtest_runs(tmp_path):
    n = 45
    dates = pd.bdate_range("2020-01-01", periods=n)
    rows = []
    for i, d in enumerate(dates):
        signal = 1 if i % 3 != 0 else 0
        car = 0.015 if signal else -0.012
        rows.append(
            {
                "event_id": f"e{i:03d}",
                "ticker": "AAA" if i % 2 else "BBB",
                "reaction_start": d.date().isoformat(),
                "event_time": d.isoformat(),
                "event_type": "earnings",
                "event_subtype": "quarterly_results",
                "event_family": "earnings_guidance",
                "source_type": "synthetic",
                "release_session": "before_open",
                "expectedness": "surprise",
                "surprise_direction": "positive" if signal else "negative",
                "surprise_magnitude": "medium",
                "materiality": 0.5 + 0.1 * signal,
                "event_status": "ok",
                "car_market_model_h1": car,
                "car_market_model_simple_h1": np.exp(car) - 1,
                "target_positive_h1": bool(signal),
                "target_direction_h1": "up" if signal else "down",
            }
        )
    event_study = tmp_path / "event_study.csv"
    pd.DataFrame(rows).to_csv(event_study, index=False)
    report = run_research_backtest(event_study, tmp_path / "bt", horizon=1, min_train=12, purge_days=1, null_iterations=10, probability_threshold=0.55)
    assert report["walk_forward"]["n_predictions"] > 0
    assert report["threshold_selection"]["threshold_mode"] == "fixed"
    assert "concentration" in report
    assert (tmp_path / "bt" / "research_backtest_report.json").exists()


def test_research_backtest_nested_threshold_mode_runs(tmp_path):
    n = 45
    dates = pd.bdate_range("2020-01-01", periods=n)
    rows = []
    for i, d in enumerate(dates):
        signal = 1 if i % 3 != 0 else 0
        car = 0.015 if signal else -0.012
        rows.append(
            {
                "event_id": f"e{i:03d}",
                "ticker": "AAA" if i % 2 else "BBB",
                "reaction_start": d.date().isoformat(),
                "event_time": d.isoformat(),
                "event_type": "earnings",
                "event_subtype": "quarterly_results",
                "event_family": "earnings_guidance",
                "source_type": "synthetic",
                "release_session": "before_open",
                "expectedness": "surprise",
                "surprise_direction": "positive" if signal else "negative",
                "surprise_magnitude": "medium",
                "materiality": 0.5 + 0.1 * signal,
                "event_status": "ok",
                "car_market_model_h1": car,
                "car_market_model_simple_h1": np.exp(car) - 1,
                "target_positive_h1": bool(signal),
                "target_direction_h1": "up" if signal else "down",
            }
        )
    event_study = tmp_path / "event_study_nested.csv"
    pd.DataFrame(rows).to_csv(event_study, index=False)

    report = run_research_backtest(
        event_study,
        tmp_path / "bt_nested",
        horizon=1,
        min_train=12,
        purge_days=1,
        null_iterations=3,
        probability_threshold=0.55,
        threshold_mode="nested_expanding",
        candidate_thresholds=[0.55, 0.60, 0.65],
        min_threshold_selection_rows=5,
    )

    assert report["threshold_selection"]["threshold_mode"] == "nested_expanding"
    assert "rows_using_default_threshold" in report["threshold_selection"]
    assert report["strategy"]["threshold_mode"] == "nested_expanding"
