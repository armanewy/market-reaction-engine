from __future__ import annotations

import pandas as pd

from mre.biotech_fresh_confirmation import (
    build_fresh_reviewed_events,
    classify_fresh_candidate,
    run_biotech_fresh_confirmation,
)


def _write_price(path, ticker: str, dates: pd.DatetimeIndex, event_moves: dict[pd.Timestamp, float] | None = None):
    event_moves = event_moves or {}
    returns = [0.0002 + event_moves.get(pd.Timestamp(d).normalize(), 0.0) for d in dates]
    adj = 100 * pd.Series(returns).add(1.0).cumprod()
    df = pd.DataFrame({"date": dates, "open": adj, "high": adj, "low": adj, "close": adj, "adj_close": adj, "volume": 1000})
    df.to_csv(path / f"{ticker}.csv", index=False)


def test_classify_fresh_candidate_rejects_soft_or_prior_rows():
    keep, reason = classify_fresh_candidate(
        pd.Series(
            {
                "biotech_catalyst_event_type": "phase_3_readout",
                "source_evidence_text": "The company will present previously announced Phase 3 results at a conference.",
                "parser_quality_flags": "publication_or_conference_notice_not_topline;previously_announced_not_new",
            }
        )
    )
    assert not keep
    assert "hard_false_positive_flag" in reason

    keep, reason = classify_fresh_candidate(
        pd.Series(
            {
                "biotech_catalyst_event_type": "phase_3_readout",
                "source_evidence_text": "The company announced positive topline results and the study met its primary endpoint.",
                "parser_quality_flags": "",
            }
        )
    )
    assert keep
    assert reason == "fresh_readout_with_new_result_language"


def test_build_fresh_reviewed_events_excludes_agent_3d_ids(tmp_path):
    raw = pd.DataFrame(
        [
            {
                "event_id": "OLD",
                "ticker": "AAA",
                "event_time": "2020-01-02T08:00:00",
                "biotech_catalyst_event_type": "phase_3_readout",
                "source_evidence_text": "announced topline results and met primary endpoint",
                "parser_quality_flags": "",
            },
            {
                "event_id": "NEW",
                "ticker": "BBB",
                "event_time": "2020-01-03T08:00:00",
                "biotech_catalyst_event_type": "fda_complete_response_letter",
                "source_evidence_text": "received a Complete Response Letter from the FDA",
                "parser_quality_flags": "",
            },
        ]
    )
    orig = pd.DataFrame([{"event_id": "OLD"}])
    out = build_fresh_reviewed_events(raw, original_events=orig, out_path=tmp_path / "fresh.csv")
    assert list(out["event_id"]) == ["NEW"]
    assert out.loc[0, "review_status"] == "reviewed"
    assert out.loc[0, "drop_reason"] == ""


def test_run_biotech_fresh_confirmation_writes_required_artifacts(tmp_path):
    dates = pd.bdate_range("2019-01-01", periods=520)
    event_dates = list(dates[160:260:4])
    rows = []
    moves = {"AAA": {}, "BBB": {}}
    for i, d in enumerate(event_dates):
        ticker = "AAA" if i % 2 == 0 else "BBB"
        positive = i % 3 != 0
        event_type = "phase_3_readout" if positive else "fda_complete_response_letter"
        evidence = (
            "The company announced positive topline results and met the primary endpoint."
            if positive
            else "The company received a Complete Response Letter from the FDA."
        )
        rows.append(
            {
                "event_id": f"FRESH{i:03d}",
                "ticker": ticker,
                "event_time": pd.Timestamp(d).replace(hour=8, minute=30).isoformat(),
                "summary": f"{ticker} {event_type}",
                "source_type": "company_press_release",
                "source_url": "https://example.test",
                "release_session": "before_open",
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
                "source_evidence_text": evidence,
                "parser_quality_flags": "",
            }
        )
        moves[ticker][pd.Timestamp(d).normalize()] = 0.03 if positive else -0.03

    raw_path = tmp_path / "fresh_raw.csv"
    pd.DataFrame(rows).to_csv(raw_path, index=False)
    original_path = tmp_path / "original.csv"
    pd.DataFrame([{"event_id": "AGENT_3D_ROW"}]).to_csv(original_path, index=False)
    parser_errors = tmp_path / "parser_errors.csv"
    pd.DataFrame([{"status": "ok"}]).to_csv(parser_errors, index=False)
    shares = tmp_path / "shares.csv"
    pd.DataFrame(
        [
            {"ticker": "AAA", "filed_at": "2019-01-01", "shares_outstanding_before_event": 10_000_000},
            {"ticker": "BBB", "filed_at": "2019-01-01", "shares_outstanding_before_event": 20_000_000},
        ]
    ).to_csv(shares, index=False)

    prices = tmp_path / "prices"
    prices.mkdir()
    _write_price(prices, "SPY", dates)
    _write_price(prices, "XBI", dates)
    _write_price(prices, "AAA", dates, moves["AAA"])
    _write_price(prices, "BBB", dates, moves["BBB"])

    report = run_biotech_fresh_confirmation(
        raw_events_path=raw_path,
        original_event_study_path=original_path,
        parser_errors_path=parser_errors,
        shares_context_path=shares,
        prices_dir=prices,
        out_dir=tmp_path / "artifacts",
        fresh_events_out=tmp_path / "fresh_events.csv",
        horizons=(1, 3, 10),
        min_train=8,
        purge_days=1,
        null_iterations=5,
        min_estimation_observations=20,
        estimation_window=60,
    )

    assert report["decision"] in {
        "fresh-confirmed, continue to leakage/execution audit",
        "promising but underpowered",
        "failed fresh confirmation",
        "parser/context issue found",
        "timestamp/leakage issue found",
    }
    out = tmp_path / "artifacts"
    assert (out / "biotech_catalyst_fresh_event_study.csv").exists()
    assert (out / "biotech_catalyst_fresh_base_rates.csv").exists()
    assert (out / "biotech_catalyst_fresh_walk_forward_predictions.csv").exists()
    assert (out / "biotech_catalyst_fresh_backtest_report.json").exists()
    assert (out / "biotech_catalyst_fresh_placebo_report.json").exists()
    assert (out / "biotech_catalyst_fresh_peer_report.json").exists()
    assert (out / "biotech_catalyst_fresh_null_shuffle_report.json").exists()
    assert (out / "biotech_catalyst_fresh_outlier_robustness.md").exists()
    assert (out / "biotech_catalyst_agent_3e_report.md").exists()

