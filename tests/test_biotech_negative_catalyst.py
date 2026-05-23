from __future__ import annotations

import pandas as pd

from mre.biotech_negative_catalyst import (
    build_negative_catalyst_event_study,
    build_negative_catalyst_timestamp_repair_audit,
    negative_binary_catalyst_mask,
    negative_catalyst_base_rates,
    run_biotech_negative_catalyst_confirmation,
    run_biotech_negative_catalyst_corrected_confirmation,
    run_biotech_negative_catalyst_timestamp_repair,
)


def _write_price(path, ticker: str, dates: pd.DatetimeIndex, event_moves: dict[pd.Timestamp, float] | None = None):
    event_moves = event_moves or {}
    returns = [0.0001 + event_moves.get(pd.Timestamp(d).normalize(), 0.0) for d in dates]
    adj = 100 * pd.Series(returns).add(1.0).cumprod()
    df = pd.DataFrame({"date": dates, "open": adj, "high": adj, "low": adj, "close": adj, "adj_close": adj, "volume": 10000})
    df.to_csv(path / f"{ticker}.csv", index=False)


def _event_row(event_id: str, ticker: str, event_time: pd.Timestamp, event_type: str, car: float, split: str) -> dict[str, object]:
    return {
        "event_id": event_id,
        "ticker": ticker,
        "event_time": event_time.replace(hour=8, minute=30).isoformat(),
        "event_type": event_type,
        "event_subtype": event_type,
        "event_family": "biotech_fda_clinical_catalyst",
        "summary": f"{ticker} {event_type}",
        "source_type": "company_press_release",
        "source_url": "https://example.test",
        "release_session": "before_open",
        "sector_benchmark": "XBI",
        "event_status": "ok",
        "reaction_start": event_time.date().isoformat(),
        "biotech_catalyst_event_type": event_type,
        "event_direction_pre_price": "negative",
        "binary_catalyst_flag": True,
        "designation_only_flag": False,
        "clinical_trial_readout_flag": event_type in {"phase_2_readout", "phase_3_readout", "pivotal_trial_readout"},
        "regulatory_decision_flag": event_type == "fda_complete_response_letter",
        "trial_failure_flag": event_type in {"endpoint_failure", "phase_2_readout", "phase_3_readout"},
        "safety_negative_flag": event_type == "safety_signal",
        "endpoint_met": False,
        "trial_phase": "phase_3" if event_type in {"phase_3_readout", "endpoint_failure"} else "",
        "market_cap_bucket": "small_300m_2b",
        "car_sector_adj_h1": car,
        "car_sector_adj_h3": car * 1.1,
        "car_sector_adj_h10": car * 0.9,
        "dataset_split": split,
    }


def test_negative_binary_catalyst_mask_excludes_positive_and_designation_rows():
    df = pd.DataFrame(
        [
            {
                "biotech_catalyst_event_type": "fda_complete_response_letter",
                "event_direction_pre_price": "negative",
                "binary_catalyst_flag": True,
                "designation_only_flag": False,
            },
            {
                "biotech_catalyst_event_type": "phase_3_readout",
                "event_direction_pre_price": "positive",
                "binary_catalyst_flag": True,
                "designation_only_flag": False,
                "endpoint_met": True,
            },
            {
                "biotech_catalyst_event_type": "fast_track_designation",
                "event_direction_pre_price": "negative",
                "binary_catalyst_flag": False,
                "designation_only_flag": True,
            },
            {
                "biotech_catalyst_event_type": "phase_3_readout",
                "event_direction_pre_price": "negative",
                "binary_catalyst_flag": True,
                "designation_only_flag": False,
                "endpoint_met": False,
            },
        ]
    )

    assert list(negative_binary_catalyst_mask(df)) == [True, False, False, True]


def test_negative_base_rates_include_fresh_and_combined_splits():
    original = pd.DataFrame([_event_row("O1", "AAA", pd.Timestamp("2020-01-10"), "trial_halt", -0.10, "original")])
    fresh = pd.DataFrame([_event_row("F1", "BBB", pd.Timestamp("2020-02-10"), "phase_3_readout", -0.08, "fresh")])
    events = build_negative_catalyst_event_study(original, fresh)
    rates = negative_catalyst_base_rates(events)

    all_h1 = rates[(rates["dataset_split"] == "combined") & (rates["group_name"] == "all") & (rates["horizon"] == 1)]
    fresh_h1 = rates[(rates["dataset_split"] == "fresh") & (rates["group_name"] == "all") & (rates["horizon"] == 1)]
    assert int(all_h1.iloc[0]["n"]) == 2
    assert int(fresh_h1.iloc[0]["n"]) == 1
    assert float(all_h1.iloc[0]["sign_accuracy"]) == 1.0


def test_run_biotech_negative_catalyst_confirmation_writes_required_artifacts(tmp_path):
    dates = pd.bdate_range("2019-01-01", periods=360)
    tickers = ["AAA", "BBB", "CCC", "DDD"]
    event_types = ["fda_complete_response_letter", "trial_halt", "safety_signal", "phase_3_readout"]
    rows = []
    moves = {ticker: {} for ticker in tickers}
    for i, d in enumerate(dates[160:240:4]):
        ticker = tickers[i % len(tickers)]
        event_type = event_types[i % len(event_types)]
        split = "original" if i < 8 else "fresh"
        event_id = ("O" if split == "original" else "F") + f"{i:03d}"
        rows.append(_event_row(event_id, ticker, pd.Timestamp(d), event_type, -0.04 - (i % 3) * 0.005, split))
        moves[ticker][pd.Timestamp(d).normalize()] = -0.04

    original_path = tmp_path / "original.csv"
    fresh_path = tmp_path / "fresh.csv"
    pd.DataFrame([r for r in rows if r["dataset_split"] == "original"]).to_csv(original_path, index=False)
    pd.DataFrame([r for r in rows if r["dataset_split"] == "fresh"]).to_csv(fresh_path, index=False)

    prices = tmp_path / "prices"
    prices.mkdir()
    _write_price(prices, "SPY", dates)
    _write_price(prices, "XBI", dates)
    for ticker in tickers:
        _write_price(prices, ticker, dates, moves[ticker])

    report = run_biotech_negative_catalyst_confirmation(
        original_event_study_path=original_path,
        fresh_event_study_path=fresh_path,
        original_source_documents_path=None,
        fresh_source_documents_path=None,
        prices_dir=prices,
        out_dir=tmp_path / "artifacts",
        estimation_window=60,
        estimation_gap=5,
        min_estimation_observations=30,
    )

    assert report["decision"] in {
        "negative-catalyst slice fresh-confirmed, continue to final audit",
        "promising but underpowered",
        "failed confirmation",
        "execution unrealistic",
        "outlier-driven",
        "timestamp issue found",
    }
    out = tmp_path / "artifacts"
    assert (out / "biotech_negative_catalyst_event_study.csv").exists()
    assert (out / "biotech_negative_catalyst_base_rates.csv").exists()
    assert (out / "biotech_negative_catalyst_placebo_report.json").exists()
    assert (out / "biotech_negative_catalyst_peer_report.json").exists()
    assert (out / "biotech_negative_catalyst_outlier_report.md").exists()
    assert (out / "biotech_negative_catalyst_execution_stress.md").exists()
    assert (out / "biotech_negative_catalyst_agent_3g_report.md").exists()


def test_timestamp_repair_shifts_after_close_to_next_trading_day(tmp_path):
    dates = pd.bdate_range("2024-01-02", periods=10)
    prices = tmp_path / "prices"
    prices.mkdir()
    _write_price(prices, "AAA", dates)
    event = pd.DataFrame([_event_row("E1", "AAA", dates[2], "fda_complete_response_letter", -0.10, "fresh")])
    sources = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "AAA",
                "source_type": "sec_primary_filing",
                "event_time": pd.Timestamp(dates[2]).replace(hour=22, minute=0).tz_localize("UTC").isoformat(),
            }
        ]
    )

    audit = build_negative_catalyst_timestamp_repair_audit(event, source_documents=sources, prices_dir=prices)

    assert audit.loc[0, "release_session"] == "after_close"
    assert audit.loc[0, "reaction_window_start"] == dates[3].date().isoformat()
    assert bool(audit.loc[0, "original_reaction_window_before_first_tradable"]) is True
    assert bool(audit.loc[0, "model_eligible"]) is True


def test_run_timestamp_repair_writes_required_artifacts(tmp_path):
    dates = pd.bdate_range("2024-01-02", periods=80)
    prices = tmp_path / "prices"
    prices.mkdir()
    _write_price(prices, "SPY", dates)
    _write_price(prices, "XBI", dates)
    _write_price(prices, "AAA", dates)
    _write_price(prices, "BBB", dates)

    original = pd.DataFrame(
        [
            _event_row("O1", "AAA", dates[40], "trial_halt", -0.08, "original"),
            _event_row("O2", "BBB", dates[42], "safety_signal", -0.05, "original"),
        ]
    )
    fresh = pd.DataFrame(
        [
            _event_row("F1", "AAA", dates[44], "fda_complete_response_letter", -0.09, "fresh"),
            _event_row("F2", "BBB", dates[46], "phase_3_readout", -0.07, "fresh"),
        ]
    )
    original_path = tmp_path / "original.csv"
    fresh_path = tmp_path / "fresh.csv"
    original.to_csv(original_path, index=False)
    fresh.to_csv(fresh_path, index=False)
    source_rows = []
    for row in pd.concat([original, fresh], ignore_index=True).itertuples(index=False):
        ts = pd.Timestamp(row.event_time).normalize().replace(hour=12, minute=0).tz_localize("UTC")
        source_rows.append({"event_id": row.event_id, "ticker": row.ticker, "source_type": "sec_primary_filing", "event_time": ts.isoformat()})
    sources_path = tmp_path / "sources.csv"
    pd.DataFrame(source_rows).to_csv(sources_path, index=False)

    report = run_biotech_negative_catalyst_timestamp_repair(
        original_event_study_path=original_path,
        fresh_event_study_path=fresh_path,
        original_source_documents_path=sources_path,
        fresh_source_documents_path=None,
        prices_dir=prices,
        out_dir=tmp_path / "artifacts",
        min_train=2,
    )

    assert report["decision"] in {
        "timestamp repair passes, ready for corrected confirmation",
        "underpowered after timestamp repair",
        "timestamp issue invalidates negative catalyst slice",
        "duplicate issue found",
    }
    out = tmp_path / "artifacts"
    assert (out / "biotech_negative_catalyst_timestamp_repaired_events.csv").exists()
    assert (out / "biotech_negative_catalyst_timestamp_audit.csv").exists()
    assert (out / "biotech_negative_catalyst_duplicate_audit.csv").exists()
    assert (out / "biotech_negative_catalyst_agent_3i_report.md").exists()


def test_run_corrected_confirmation_uses_repaired_windows(tmp_path):
    dates = pd.bdate_range("2024-01-02", periods=180)
    prices = tmp_path / "prices"
    prices.mkdir()
    _write_price(prices, "SPY", dates)
    _write_price(prices, "XBI", dates)
    _write_price(prices, "AAA", dates, {pd.Timestamp(d).normalize(): -0.03 for d in dates[130:150:2]})
    _write_price(prices, "BBB", dates, {pd.Timestamp(d).normalize(): -0.025 for d in dates[131:151:2]})

    repaired_rows = []
    audit_rows = []
    for i, d in enumerate(dates[130:150]):
        ticker = "AAA" if i % 2 == 0 else "BBB"
        split = "original" if i < 8 else "fresh"
        row = _event_row(f"E{i:03d}", ticker, pd.Timestamp(d), "trial_halt", -0.04, split)
        row["reaction_window_start"] = pd.Timestamp(d).date().isoformat()
        row["selected_event_time"] = pd.Timestamp(d).replace(hour=12).tz_localize("UTC").isoformat()
        row["first_tradable_timestamp"] = pd.Timestamp(d).replace(hour=9, minute=30).tz_localize("America/New_York").isoformat()
        row["model_eligible"] = True
        row["duplicate_model_exclusion_flag"] = False
        repaired_rows.append(row)
        audit_rows.append(
            {
                "event_id": row["event_id"],
                "ticker": ticker,
                "release_session": "before_open",
                "first_tradable_timestamp": row["first_tradable_timestamp"],
                "timestamp_ambiguous": False,
                "model_eligible": True,
            }
        )

    repaired_path = tmp_path / "repaired.csv"
    audit_path = tmp_path / "timestamp.csv"
    duplicate_path = tmp_path / "duplicate.csv"
    pd.DataFrame(repaired_rows).to_csv(repaired_path, index=False)
    pd.DataFrame(audit_rows).to_csv(audit_path, index=False)
    pd.DataFrame(
        [
            {
                "event_id": row["event_id"],
                "ticker": row["ticker"],
                "same_key_event_count": 1,
                "duplicate_risk_level": "low",
            }
            for row in repaired_rows
        ]
    ).to_csv(duplicate_path, index=False)

    report = run_biotech_negative_catalyst_corrected_confirmation(
        repaired_events_path=repaired_path,
        timestamp_audit_path=audit_path,
        duplicate_audit_path=duplicate_path,
        prices_dir=prices,
        out_dir=tmp_path / "artifacts",
        estimation_window=40,
        estimation_gap=5,
        min_estimation_observations=25,
    )

    assert report["decision"] in {
        "corrected confirmation passed; continue to final execution/liquidity audit",
        "promising but underpowered",
        "failed corrected confirmation",
        "execution unrealistic",
        "outlier-driven",
        "timestamp issue reappeared",
    }
    out = tmp_path / "artifacts"
    assert (out / "biotech_negative_catalyst_corrected_event_study.csv").exists()
    assert (out / "biotech_negative_catalyst_corrected_base_rates.csv").exists()
    assert (out / "biotech_negative_catalyst_corrected_placebo_report.json").exists()
    assert (out / "biotech_negative_catalyst_corrected_peer_report.json").exists()
    assert (out / "biotech_negative_catalyst_corrected_outlier_report.md").exists()
    assert (out / "biotech_negative_catalyst_corrected_execution_stress.md").exists()
    assert (out / "biotech_negative_catalyst_agent_3j_report.md").exists()
