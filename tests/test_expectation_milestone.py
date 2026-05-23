from pathlib import Path

import pandas as pd

from mre.analyst_revisions import compute_analyst_revision_features, merge_analyst_revisions
from mre.events import make_event_template
from mre.expectations import compute_expectation_features, merge_external_expectations
from mre.options import compute_implied_moves, merge_options_implied_moves
from mre.release_times import infer_release_session, merge_release_times


def _events(tmp_path: Path) -> Path:
    events = tmp_path / "events.csv"
    make_event_template(
        events,
        [
            {
                "event_id": "e1",
                "ticker": "ACME",
                "event_time": "2024-05-01T16:05:00",
                "event_type": "earnings",
                "summary": "ACME earnings.",
                "release_session": "after_close",
            }
        ],
    )
    return events


def test_release_times_merge_updates_event_time_and_session(tmp_path: Path):
    events = _events(tmp_path)
    releases = tmp_path / "releases.csv"
    pd.DataFrame(
        [
            {
                "event_id": "e1",
                "ticker": "ACME",
                "exact_release_time": "2024-05-01T08:01:00",
                "release_time_confidence": "primary_source",
            }
        ]
    ).to_csv(releases, index=False)
    out = tmp_path / "events_with_releases.csv"
    merged = merge_release_times(events, releases, out)
    assert out.exists()
    assert merged.loc[0, "release_session"] == "before_open"
    assert str(pd.Timestamp(merged.loc[0, "event_time"])) == "2024-05-01 08:01:00"
    assert infer_release_session("2024-05-01T12:00:00") == "intraday"


def test_expectation_features_include_margin_and_guidance_eps():
    df = compute_expectation_features(
        pd.DataFrame(
            [
                {
                    "event_id": "e1",
                    "ticker": "ACME",
                    "consensus_eps": 1.0,
                    "actual_eps": 1.2,
                    "consensus_forward_eps": 1.1,
                    "guidance_eps_low": 1.15,
                    "guidance_eps_high": 1.25,
                    "consensus_revenue": 1000,
                    "actual_revenue": 1050,
                    "consensus_forward_revenue": 1100,
                    "guidance_revenue_low": 1120,
                    "guidance_revenue_high": 1180,
                    "consensus_gross_margin": "60%",
                    "actual_gross_margin": "63%",
                    "consensus_forward_gross_margin": 0.61,
                    "guidance_gross_margin_low": 0.62,
                    "guidance_gross_margin_high": 0.64,
                }
            ]
        )
    )
    assert df.loc[0, "guidance_eps_mid"] == 1.2
    assert round(float(df.loc[0, "guidance_eps_surprise_pct"]), 6) == round((1.2 - 1.1) / 1.1, 6)
    assert round(float(df.loc[0, "actual_gross_margin"]), 6) == 0.63
    assert round(float(df.loc[0, "gross_margin_surprise"]), 6) == 0.03
    assert df.loc[0, "has_expectation_data"]


def test_options_implied_move_from_atm_straddle(tmp_path: Path):
    events = _events(tmp_path)
    options = tmp_path / "options.csv"
    pd.DataFrame(
        [
            {
                "event_id": "e1",
                "ticker": "ACME",
                "quote_time": "2024-05-01T15:55:00",
                "expiration": "2024-05-03",
                "underlying_price": 100,
                "strike": 100,
                "call_bid": 2.9,
                "call_ask": 3.1,
                "put_bid": 2.4,
                "put_ask": 2.6,
            },
            {
                "event_id": "e1",
                "ticker": "ACME",
                "quote_time": "2024-05-01T15:56:00",
                "expiration": "2024-05-03",
                "underlying_price": 100,
                "strike": 120,
                "call_mid": 0.1,
                "put_mid": 20.0,
            },
        ]
    ).to_csv(options, index=False)
    moves, diag = compute_implied_moves(events, options)
    assert diag.events_with_implied_move == 1
    assert round(float(moves.loc[0, "implied_move_pct"]), 6) == 0.055
    merged, _ = merge_options_implied_moves(events, options, tmp_path / "merged.csv")
    assert "implied_move_pct" in merged.columns


def test_analyst_revision_features_and_consensus_fill(tmp_path: Path):
    events = _events(tmp_path)
    revisions = tmp_path / "revisions.csv"
    rows = []
    for analyst, old, new in [("a1", 1.0, 1.2), ("a2", 1.1, 1.05), ("a3", 0.9, 1.0)]:
        rows.append({"event_id": "e1", "ticker": "ACME", "estimate_time": "2024-04-01T12:00:00", "analyst_id": analyst, "metric": "eps", "estimate_value": old})
        rows.append({"event_id": "e1", "ticker": "ACME", "estimate_time": "2024-04-30T12:00:00", "analyst_id": analyst, "metric": "eps", "estimate_value": new})
    rows.append({"event_id": "e1", "ticker": "ACME", "estimate_time": "2024-04-30T12:00:00", "analyst_id": "a1", "metric": "revenue", "estimate_value": 1000})
    pd.DataFrame(rows).to_csv(revisions, index=False)
    features, diag = compute_analyst_revision_features(events, revisions, windows=(7, 30), metrics=("eps", "revenue"))
    assert diag.events_with_revision_features == 1
    assert features.loc[0, "analyst_eps_count"] == 3.0
    assert features.loc[0, "analyst_eps_revision_count_7d"] == 3.0
    assert features.loc[0, "analyst_eps_revision_pct_up_7d"] == 2 / 3
    merged, _ = merge_analyst_revisions(events, revisions, tmp_path / "events_with_revisions.csv", metrics=("eps", "revenue"))
    assert "consensus_eps" in merged.columns
    assert round(float(merged.loc[0, "consensus_eps"]), 6) == round((1.2 + 1.05 + 1.0) / 3, 6)
