from __future__ import annotations

import numpy as np
import pandas as pd

from mre.backtest import (
    calibration_table,
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
    assert (tmp_path / "bt" / "research_backtest_report.json").exists()
