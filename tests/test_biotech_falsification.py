from __future__ import annotations

import pandas as pd

from mre.biotech_falsification import (
    biotech_base_rate_table,
    prepare_biotech_falsification_events,
    run_biotech_catalyst_falsification_pass,
)


def _write_price(path, ticker: str, dates: pd.DatetimeIndex, event_moves: dict[pd.Timestamp, float] | None = None):
    event_moves = event_moves or {}
    returns = []
    for d in dates:
        returns.append(0.0002 + event_moves.get(pd.Timestamp(d).normalize(), 0.0))
    adj = 100 * pd.Series(returns).add(1.0).cumprod()
    df = pd.DataFrame({"date": dates, "open": adj, "high": adj, "low": adj, "close": adj, "adj_close": adj, "volume": 1000})
    df.to_csv(path / f"{ticker}.csv", index=False)


def test_prepare_biotech_falsification_events_maps_reviewed_labels(tmp_path):
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "AAA",
                "event_time": "2020-06-01T08:30:00",
                "summary": "AAA announced topline results",
                "review_status": "reviewed",
                "drop_reason": "",
                "biotech_catalyst_event_type": "phase_3_readout",
                "event_direction_pre_price": "positive",
                "binary_catalyst_flag": True,
                "designation_only_flag": False,
                "clinical_trial_readout_flag": True,
                "regulatory_decision_flag": False,
                "endpoint_met": True,
                "safety_negative_flag": False,
                "market_cap_before_event": 1_000_000_000,
                "sector_benchmark": "",
            },
            {
                "event_id": "E2",
                "ticker": "AAA",
                "event_time": "2020-06-02T08:30:00",
                "summary": "AAA pipeline update",
                "review_status": "rejected",
                "drop_reason": "soft_update",
                "biotech_catalyst_event_type": "unknown",
            },
        ]
    )
    out = prepare_biotech_falsification_events(events, sector_benchmark="XBI", out_path=tmp_path / "analysis.csv")
    assert len(out) == 1
    assert out.loc[0, "event_type"] == "phase_3_readout"
    assert out.loc[0, "event_subtype"] == "phase_3_readout"
    assert out.loc[0, "surprise_direction"] == "positive"
    assert out.loc[0, "primary_endpoint_met"] == "true"
    assert out.loc[0, "sector_benchmark"] == "XBI"


def test_biotech_falsification_pass_writes_required_artifacts(tmp_path):
    dates = pd.bdate_range("2019-01-01", periods=520)
    event_dates = list(dates[160:260:4])
    rows = []
    moves = {"AAA": {}, "BBB": {}}
    for i, d in enumerate(event_dates):
        ticker = "AAA" if i % 2 == 0 else "BBB"
        positive = i % 3 != 0
        event_type = "phase_3_readout" if positive else "fda_complete_response_letter"
        rows.append(
            {
                "event_id": f"E{i:03d}",
                "ticker": ticker,
                "event_time": pd.Timestamp(d).replace(hour=8, minute=30).isoformat(),
                "summary": f"{ticker} {event_type}",
                "source_type": "company_press_release",
                "source_url": "https://example.test",
                "release_session": "before_open",
                "review_status": "reviewed",
                "drop_reason": "",
                "biotech_catalyst_event_type": event_type,
                "event_direction_pre_price": "positive" if positive else "negative",
                "binary_catalyst_flag": True,
                "designation_only_flag": False,
                "clinical_trial_readout_flag": positive,
                "regulatory_decision_flag": not positive,
                "trial_failure_flag": not positive,
                "endpoint_met": positive,
                "safety_negative_flag": False,
                "trial_phase": "phase_3",
                "materiality": 0.8,
                "market_cap_before_event": 1_000_000_000 if ticker == "AAA" else 5_000_000_000,
                "pre_event_market_adjusted_return_20d": 0.02 if positive else -0.03,
                "sector_benchmark": "XBI",
                "source_evidence_text": "source-backed catalyst",
            }
        )
        moves[ticker][pd.Timestamp(d).normalize()] = 0.03 if positive else -0.03

    events_path = tmp_path / "events.csv"
    pd.DataFrame(rows).to_csv(events_path, index=False)
    prices = tmp_path / "prices"
    prices.mkdir()
    _write_price(prices, "SPY", dates)
    _write_price(prices, "XBI", dates)
    _write_price(prices, "AAA", dates, moves["AAA"])
    _write_price(prices, "BBB", dates, moves["BBB"])

    report = run_biotech_catalyst_falsification_pass(
        events_path=events_path,
        features_path=None,
        prices_dir=prices,
        out_dir=tmp_path / "artifacts",
        horizons=(1, 3, 10),
        min_train=8,
        purge_days=1,
        null_iterations=5,
        min_estimation_observations=20,
        estimation_window=60,
    )

    assert report["decision"] in {
        "promising, require fresh-data confirmation",
        "underpowered",
        "failed falsification",
        "parser/context issue found",
        "timestamp/leakage issue found",
    }
    out = tmp_path / "artifacts"
    assert (out / "biotech_catalyst_event_study.csv").exists()
    assert (out / "biotech_catalyst_base_rates.csv").exists()
    assert (out / "biotech_catalyst_walk_forward_predictions.csv").exists()
    assert (out / "biotech_catalyst_backtest_report.json").exists()
    assert (out / "biotech_catalyst_placebo_report.json").exists()
    assert (out / "biotech_catalyst_peer_report.json").exists()
    assert (out / "biotech_catalyst_null_shuffle_report.json").exists()
    assert (out / "biotech_catalyst_agent_3d_report.md").exists()

    base_rates = biotech_base_rate_table(out / "biotech_catalyst_event_study.csv")
    assert {"biotech_catalyst_event_type", "event_direction_pre_price"}.issubset(set(base_rates["group_name"]))
