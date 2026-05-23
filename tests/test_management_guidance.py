from __future__ import annotations

from pathlib import Path

import pandas as pd

from mre.management_guidance import build_management_guidance_bridge


def test_management_guidance_bridge_uses_immediate_prior_guidance(tmp_path: Path):
    features = pd.DataFrame(
        [
            {
                "event_id": "AAA_1",
                "ticker": "AAA",
                "event_time": "2024-01-01T16:05:00",
                "guidance_revenue_mid": 1000.0,
                "guidance_revenue_mid_confidence": 0.92,
            },
            {
                "event_id": "AAA_2",
                "ticker": "AAA",
                "event_time": "2024-04-01T16:05:00",
                "actual_revenue": 950.0,
                "actual_revenue_confidence": 0.88,
                "guidance_revenue_mid": 1100.0,
                "guidance_revenue_mid_confidence": 0.92,
            },
        ]
    )
    features_path = tmp_path / "features.csv"
    out_path = tmp_path / "bridge.csv"
    features.to_csv(features_path, index=False)

    bridge, diag = build_management_guidance_bridge(features_path, out_path)

    assert diag.ready_for_model == 1
    row = bridge[bridge["event_id"] == "AAA_2"].iloc[0]
    assert row["bridge_status"] == "ready_for_model"
    assert row["prior_event_id"] == "AAA_1"
    assert row["prior_guidance_revenue_mid"] == 1000.0
    assert row["actual_vs_prior_management_guidance"] == -50.0
    assert row["actual_vs_prior_management_guidance_pct"] == -0.05
    assert row["surprise_direction"] == "negative"


def test_management_guidance_bridge_flags_implausible_period_ratio(tmp_path: Path):
    features = pd.DataFrame(
        [
            {
                "event_id": "AAA_1",
                "ticker": "AAA",
                "event_time": "2024-01-01T16:05:00",
                "guidance_revenue_mid": 1000.0,
                "guidance_revenue_mid_confidence": 0.92,
            },
            {
                "event_id": "AAA_2",
                "ticker": "AAA",
                "event_time": "2024-04-01T16:05:00",
                "actual_revenue": 5000.0,
                "actual_revenue_confidence": 0.88,
                "guidance_revenue_mid": 1100.0,
                "guidance_revenue_mid_confidence": 0.92,
            },
        ]
    )
    features_path = tmp_path / "features.csv"
    out_path = tmp_path / "bridge.csv"
    features.to_csv(features_path, index=False)

    bridge, diag = build_management_guidance_bridge(features_path, out_path)

    assert diag.ready_for_model == 0
    row = bridge[bridge["event_id"] == "AAA_2"].iloc[0]
    assert row["bridge_status"] == "ambiguous_period"
    assert "actual_to_prior_guidance_ratio_out_of_bounds" in row["parser_quality_flags"]

