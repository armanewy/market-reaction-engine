from __future__ import annotations

import pandas as pd

from mre.government_contract_falsification import (
    government_contract_base_rate_table,
    prepare_government_contract_falsification_events,
    run_government_contract_falsification_pass,
)


def _write_price(path, ticker: str, dates: pd.DatetimeIndex, event_moves: dict[pd.Timestamp, float] | None = None):
    event_moves = event_moves or {}
    returns = []
    for d in dates:
        returns.append(0.0002 + event_moves.get(pd.Timestamp(d).normalize(), 0.0))
    adj = 100 * pd.Series(returns).add(1.0).cumprod()
    df = pd.DataFrame({"date": dates, "open": adj, "high": adj, "low": adj, "close": adj, "adj_close": adj, "volume": 1000})
    df.to_csv(path / f"{ticker}.csv", index=False)


def test_prepare_government_contract_falsification_events_filters_public_links(tmp_path):
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "KTOS",
                "event_time": "2024-01-02T08:30:00",
                "release_session": "before_open",
                "review_status": "approved",
                "model_eligible_public_announcement_flag": True,
                "public_announcement_link_confidence": 0.9,
                "public_announcement_source_type": "company_press_release",
                "duplicate_status": "primary",
                "recipient_mapping_confidence": 0.9,
                "actual_funded_award_flag": True,
                "ceiling_only_flag": False,
                "obligated_amount": 50_000_000,
                "award_amount": 50_000_000,
                "obligated_amount_pct_market_cap": 0.05,
                "award_amount_pct_market_cap": 0.05,
                "company_size_bucket": "small_cap",
                "government_contract_event_type": "new_contract_award",
            },
            {
                "event_id": "E2",
                "ticker": "KTOS",
                "event_time": "2024-01-03T12:00:00",
                "release_session": "unknown",
                "review_status": "approved",
                "model_eligible_public_announcement_flag": True,
                "public_announcement_link_confidence": 0.9,
                "duplicate_status": "primary",
                "recipient_mapping_confidence": 0.9,
                "actual_funded_award_flag": True,
                "obligated_amount_pct_market_cap": 0.05,
            },
        ]
    )
    prices = tmp_path / "prices"
    prices.mkdir()
    (prices / "SPY.csv").write_text("date,open,high,low,close,adj_close,volume\n", encoding="utf-8")

    out, limitation = prepare_government_contract_falsification_events(events, prices_dir=prices, out_path=tmp_path / "analysis.csv")

    assert len(out) == 1
    assert out.loc[0, "event_id"] == "E1"
    assert out.loc[0, "small_mid_cap_flag"] == True
    assert out.loc[0, "sector_benchmark"] == "SPY"
    assert "ETF prices were not available" in limitation


def test_government_contract_falsification_pass_writes_required_artifacts(tmp_path):
    dates = pd.bdate_range("2023-01-02", periods=360)
    event_dates = list(dates[150:260:4])
    rows = []
    moves = {"AVAV": {}, "KTOS": {}}
    for i, d in enumerate(event_dates):
        ticker = "AVAV" if i % 2 == 0 else "KTOS"
        material = i % 3 != 0
        rows.append(
            {
                "event_id": f"G{i:03d}",
                "ticker": ticker,
                "event_time": pd.Timestamp(d).replace(hour=8, minute=30).isoformat(),
                "summary": f"{ticker} government contract award",
                "source_type": "company_press_release",
                "source_url": "https://example.test",
                "release_session": "before_open",
                "review_status": "approved",
                "model_eligible_public_announcement_flag": True,
                "public_announcement_link_confidence": 0.9,
                "public_announcement_source_type": "company_press_release",
                "duplicate_status": "primary",
                "recipient_mapping_confidence": 0.9,
                "actual_funded_award_flag": True,
                "ceiling_only_flag": False,
                "new_work_flag": True,
                "modification_flag": False,
                "option_exercise_flag": False,
                "obligated_amount": 80_000_000 if material else 2_000_000,
                "award_amount": 80_000_000 if material else 2_000_000,
                "obligated_amount_pct_market_cap": 0.05 if material else 0.001,
                "award_amount_pct_market_cap": 0.05 if material else 0.001,
                "company_size_bucket": "small_cap",
                "small_cap_flag": True,
                "government_contract_event_type": "new_contract_award",
                "agency": "Department of Defense",
                "pre_event_market_adjusted_return_20d": 0.01 if material else -0.01,
            }
        )
        moves[ticker][pd.Timestamp(d).normalize()] = 0.02 if material else -0.005

    events_path = tmp_path / "events.csv"
    pd.DataFrame(rows).to_csv(events_path, index=False)
    prices = tmp_path / "prices"
    prices.mkdir()
    _write_price(prices, "SPY", dates)
    _write_price(prices, "AVAV", dates, moves["AVAV"])
    _write_price(prices, "KTOS", dates, moves["KTOS"])

    report = run_government_contract_falsification_pass(
        events_path=events_path,
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
        "timestamp/public-awareness issue found",
        "mapping/context issue found",
        "domain not promising",
    }
    out = tmp_path / "artifacts"
    assert (out / "government_contract_event_study.csv").exists()
    assert (out / "government_contract_base_rates.csv").exists()
    assert (out / "government_contract_walk_forward_predictions.csv").exists()
    assert (out / "government_contract_backtest_report.json").exists()
    assert (out / "government_contract_placebo_report.json").exists()
    assert (out / "government_contract_peer_report.json").exists()
    assert (out / "government_contract_null_shuffle_report.json").exists()
    assert (out / "government_contract_materiality_sensitivity.md").exists()
    assert (out / "government_contract_agent_4g_report.md").exists()

    base_rates = government_contract_base_rate_table(out / "government_contract_event_study.csv")
    assert {"small_mid_cap_flag", "obligated_materiality_bucket", "agency"}.issubset(set(base_rates["group_name"]))
