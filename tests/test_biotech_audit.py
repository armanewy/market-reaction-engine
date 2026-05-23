from __future__ import annotations

import pandas as pd

from mre.biotech_audit import (
    BIOTECH_AUDIT_DECISIONS,
    build_duplicate_audit,
    build_timestamp_audit,
    run_biotech_catalyst_audit_pass,
)


def _write_price(path, ticker: str, dates: pd.DatetimeIndex, daily_move: float = 0.001):
    close = 10 * pd.Series([1.0 + daily_move] * len(dates)).cumprod()
    df = pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.99,
            "high": close * 1.01,
            "low": close * 0.98,
            "close": close,
            "adj_close": close,
            "volume": 1_000_000,
        }
    )
    df.to_csv(path / f"{ticker}.csv", index=False)


def test_timestamp_audit_flags_reaction_before_after_close_first_window(tmp_path):
    prices = tmp_path / "prices"
    prices.mkdir()
    dates = pd.bdate_range("2024-01-02", periods=5)
    _write_price(prices, "AAA", dates)

    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "AAA",
                "event_time": "2024-01-02 22:00:00",
                "release_session": "intraday",
                "reaction_start": "2024-01-02",
            }
        ]
    )
    sources = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "source_doc_id": "E1_8k",
                "source_type": "sec_primary_filing",
                "event_time": "2024-01-02T22:00:00+00:00",
            }
        ]
    )

    audit = build_timestamp_audit(events, source_documents=sources, prices_dir=prices)

    assert audit.loc[0, "session_from_sec_acceptance_et"] == "after_close"
    assert audit.loc[0, "expected_reaction_start_from_sec_session"] == "2024-01-03"
    assert audit.loc[0, "timestamp_risk_level"] == "high"
    assert bool(audit.loc[0, "reaction_start_before_expected"]) is True


def test_duplicate_audit_flags_source_mirror_and_prior_language():
    events = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "AAA",
                "reaction_start": "2024-01-02",
                "biotech_catalyst_event_type": "phase_3_readout",
                "drug_asset": "Drug A",
                "indication": "Disease",
                "source_evidence_text": "Previously announced topline results will be presented at a conference.",
            }
        ]
    )
    sources = pd.DataFrame(
        [
            {"event_id": "E1", "source_doc_id": "E1_8k", "source_type": "sec_primary_filing"},
            {"event_id": "E1", "source_doc_id": "E1_ex99", "source_type": "sec_exhibit"},
        ]
    )

    audit = build_duplicate_audit(events, source_documents=sources)

    assert bool(audit.loc[0, "source_mirror_flag"]) is True
    assert bool(audit.loc[0, "prior_announcement_language_flag"]) is True
    assert bool(audit.loc[0, "conference_publication_language_flag"]) is True
    assert audit.loc[0, "duplicate_risk_level"] == "medium"


def test_biotech_audit_pass_writes_required_artifacts(tmp_path):
    dates = pd.bdate_range("2023-01-02", periods=120)
    prices = tmp_path / "prices"
    prices.mkdir()
    _write_price(prices, "AAA", dates, daily_move=0.001)
    _write_price(prices, "BBB", dates, daily_move=0.0005)
    _write_price(prices, "XBI", dates, daily_move=0.0002)

    event_date = dates[90]
    event_study = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "AAA",
                "event_time": pd.Timestamp(event_date).replace(hour=13).isoformat(),
                "release_session": "before_open",
                "reaction_start": event_date.date().isoformat(),
                "event_status": "ok",
                "biotech_catalyst_event_type": "fda_complete_response_letter",
                "event_direction_pre_price": "negative",
                "binary_catalyst_flag": True,
                "trial_failure_flag": True,
                "market_cap_bucket": "small_300m_2b",
                "market_cap_before_event": 900_000_000,
                "trial_phase": "phase_3",
                "indication": "Disease",
                "source_evidence_text": "Company received a complete response letter.",
                "car_sector_adj_h1": -0.08,
                "car_sector_adj_h3": -0.06,
                "car_sector_adj_h10": -0.04,
            }
        ]
    )
    event_study_path = tmp_path / "event_study.csv"
    event_study.to_csv(event_study_path, index=False)

    sources = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "source_doc_id": "E1_8k",
                "source_type": "sec_primary_filing",
                "event_time": pd.Timestamp(event_date).replace(hour=13).isoformat() + "+00:00",
            },
            {
                "event_id": "E1",
                "source_doc_id": "E1_ex99",
                "source_type": "sec_exhibit",
                "event_time": pd.Timestamp(event_date).replace(hour=13).isoformat() + "+00:00",
            },
        ]
    )
    sources_path = tmp_path / "sources.csv"
    sources.to_csv(sources_path, index=False)

    trades = pd.DataFrame(
        [
            {
                "event_id": "E1",
                "ticker": "AAA",
                "reaction_start": event_date.date().isoformat(),
                "position": -1,
                "gross_event_return": -0.0769,
                "net_event_return": 0.0759,
            }
        ]
    )
    trades_path = tmp_path / "trades.csv"
    trades.to_csv(trades_path, index=False)

    out = tmp_path / "artifacts"
    report = run_biotech_catalyst_audit_pass(
        event_study_path=event_study_path,
        source_documents_path=sources_path,
        strategy_trades_path=trades_path,
        prices_dir=prices,
        out_dir=out,
    )

    assert report["decision"] in BIOTECH_AUDIT_DECISIONS
    assert (out / "biotech_catalyst_timestamp_audit.csv").exists()
    assert (out / "biotech_catalyst_duplicate_audit.csv").exists()
    assert (out / "biotech_catalyst_outlier_audit.md").exists()
    assert (out / "biotech_catalyst_execution_stress_report.md").exists()
    assert (out / "biotech_catalyst_agent_3f_report.md").exists()
