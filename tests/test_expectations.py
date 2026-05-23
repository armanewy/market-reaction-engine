from pathlib import Path

import pandas as pd

from mre.expectations import compute_expectation_features, make_expectations_template, apply_expectations_to_events


def test_compute_expectation_features_derives_surprises():
    df = pd.DataFrame(
        [
            {
                "event_id": "e1",
                "consensus_eps": 1.00,
                "actual_eps": 1.10,
                "consensus_revenue": 100.0,
                "actual_revenue": 103.0,
                "consensus_forward_revenue": 110.0,
                "guidance_revenue_low": 113.0,
                "guidance_revenue_high": 115.0,
                "implied_move_pct": "5%",
            }
        ]
    )
    out = compute_expectation_features(df)
    assert round(float(out.loc[0, "eps_surprise_pct"]), 4) == 0.1
    assert round(float(out.loc[0, "revenue_surprise_pct"]), 4) == 0.03
    assert round(float(out.loc[0, "guidance_revenue_surprise_pct"]), 4) == round((114.0 - 110.0) / 110.0, 4)
    assert round(float(out.loc[0, "implied_move_pct"]), 4) == 0.05
    assert out.loc[0, "surprise_direction_inferred"] == "positive"
    assert out.loc[0, "has_expectation_data"]


def test_expectation_template_and_merge(tmp_path: Path):
    events = pd.DataFrame(
        [
            {
                "event_id": "e1",
                "ticker": "ACME",
                "event_time": "2024-02-01T16:05:00",
                "event_type": "earnings",
                "summary": "ACME earnings",
                "release_session": "after_close",
            }
        ]
    )
    events_path = tmp_path / "events.csv"
    events.to_csv(events_path, index=False)
    tmpl_path = tmp_path / "expectations.csv"
    tmpl = make_expectations_template(events_path, tmpl_path)
    assert tmpl_path.exists()
    assert tmpl.loc[0, "event_id"] == "e1"

    tmpl.loc[0, "consensus_eps"] = 1.0
    tmpl.loc[0, "actual_eps"] = 0.9
    tmpl.to_csv(tmpl_path, index=False)
    out_path = tmp_path / "events_enriched.csv"
    merged = apply_expectations_to_events(events_path, tmpl_path, out_path, fill_labels=True)
    assert out_path.exists()
    assert "eps_surprise_pct" in merged.columns
    assert merged.loc[0, "surprise_direction"] == "negative"
