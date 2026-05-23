from __future__ import annotations

from pathlib import Path

import pandas as pd

from mre.management_guidance import build_management_guidance_bridge, validate_management_guidance_bridge


def test_management_guidance_bridge_uses_immediate_prior_guidance(tmp_path: Path):
    features = pd.DataFrame(
        [
            {
                "event_id": "AAA_1",
                "ticker": "AAA",
                "event_time": "2024-01-01T16:05:00",
                "guidance_revenue_mid": 1000.0,
                "guidance_revenue_mid_confidence": 0.92,
                "guidance_revenue_mid_evidence": "For the second quarter of fiscal 2024, we expect revenue of $1.0 billion.",
            },
            {
                "event_id": "AAA_2",
                "ticker": "AAA",
                "event_time": "2024-04-01T16:05:00",
                "actual_revenue": 950.0,
                "actual_revenue_confidence": 0.88,
                "actual_revenue_evidence": "Revenue of $950 million increased sequentially.",
                "guidance_revenue_mid": 1100.0,
                "guidance_revenue_mid_confidence": 0.92,
                "guidance_revenue_mid_evidence": "For the third quarter of fiscal 2024, we expect revenue of $1.1 billion.",
                "actual_eps": -999.0,
                "actual_eps_confidence": 0.01,
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
    assert row["prior_event_gap_days"] == 91.0
    assert row["actual_vs_prior_management_guidance"] == -50.0
    assert row["actual_vs_prior_management_guidance_pct"] == -0.05
    assert row["surprise_direction"] == "negative"
    assert "actual_eps" not in bridge.columns
    assert row["period_alignment_status"] == "aligned"
    assert row["current_reported_period_label"] == "FY2024Q2"
    assert row["prior_guidance_target_period_label"] == "FY2024Q2"


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
    assert row["bridge_status"] == "ambiguous"
    assert "actual_to_prior_guidance_ratio_out_of_bounds" in row["parser_quality_flags"]


def test_management_guidance_bridge_rejects_full_year_actual_period(tmp_path: Path):
    features = pd.DataFrame(
        [
            {
                "event_id": "AAA_1",
                "ticker": "AAA",
                "event_time": "2024-01-01T16:05:00",
                "guidance_revenue_mid": 1000.0,
                "guidance_revenue_mid_confidence": 0.92,
                "guidance_revenue_mid_evidence": "For the second quarter of fiscal 2024, we expect revenue of $1.0 billion.",
            },
            {
                "event_id": "AAA_2",
                "ticker": "AAA",
                "event_time": "2024-04-01T16:05:00",
                "actual_revenue": 950.0,
                "actual_revenue_confidence": 0.88,
                "actual_revenue_evidence": "Fiscal 2024 revenue of $950 million increased year over year.",
                "guidance_revenue_mid": 1100.0,
                "guidance_revenue_mid_confidence": 0.92,
                "guidance_revenue_mid_evidence": "For the third quarter of fiscal 2024, we expect revenue of $1.1 billion.",
            },
        ]
    )
    features_path = tmp_path / "features.csv"
    out_path = tmp_path / "bridge.csv"
    features.to_csv(features_path, index=False)

    bridge, diag = build_management_guidance_bridge(features_path, out_path)

    assert diag.ready_for_model == 0
    row = bridge[bridge["event_id"] == "AAA_2"].iloc[0]
    assert row["bridge_status"] == "period_ambiguous"
    assert row["period_alignment_status"] == "rejected"
    assert "full-year" in row["period_alignment_notes"]


def test_management_guidance_bridge_rejects_gap_too_long(tmp_path: Path):
    features = pd.DataFrame(
        [
            {
                "event_id": "AAA_1",
                "ticker": "AAA",
                "event_time": "2023-01-01T16:05:00",
                "guidance_revenue_mid": 1000.0,
                "guidance_revenue_mid_confidence": 0.92,
            },
            {
                "event_id": "AAA_2",
                "ticker": "AAA",
                "event_time": "2024-04-01T16:05:00",
                "actual_revenue": 950.0,
                "actual_revenue_confidence": 0.88,
            },
        ]
    )
    features_path = tmp_path / "features.csv"
    out_path = tmp_path / "bridge.csv"
    features.to_csv(features_path, index=False)

    bridge, diag = build_management_guidance_bridge(features_path, out_path)

    assert diag.ready_for_model == 0
    row = bridge[bridge["event_id"] == "AAA_2"].iloc[0]
    assert row["bridge_status"] == "prior_event_gap_too_long"


def test_management_guidance_bridge_rejects_gap_too_short(tmp_path: Path):
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
                "event_time": "2024-01-15T16:05:00",
                "actual_revenue": 950.0,
                "actual_revenue_confidence": 0.88,
            },
        ]
    )
    features_path = tmp_path / "features.csv"
    out_path = tmp_path / "bridge.csv"
    features.to_csv(features_path, index=False)

    bridge, diag = build_management_guidance_bridge(features_path, out_path)

    assert diag.ready_for_model == 0
    row = bridge[bridge["event_id"] == "AAA_2"].iloc[0]
    assert row["bridge_status"] == "prior_event_gap_too_short"


def test_management_guidance_bridge_rejects_low_confidence_fields(tmp_path: Path):
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
                "actual_revenue_confidence": 0.50,
            },
            {
                "event_id": "BBB_1",
                "ticker": "BBB",
                "event_time": "2024-01-01T16:05:00",
                "guidance_revenue_mid": 1000.0,
                "guidance_revenue_mid_confidence": 0.50,
            },
            {
                "event_id": "BBB_2",
                "ticker": "BBB",
                "event_time": "2024-04-01T16:05:00",
                "actual_revenue": 950.0,
                "actual_revenue_confidence": 0.92,
            },
        ]
    )
    features_path = tmp_path / "features.csv"
    out_path = tmp_path / "bridge.csv"
    features.to_csv(features_path, index=False)

    bridge, diag = build_management_guidance_bridge(features_path, out_path)

    assert diag.ready_for_model == 0
    statuses = dict(zip(bridge["event_id"], bridge["bridge_status"]))
    assert statuses["AAA_2"] == "low_actual_revenue_confidence"
    assert statuses["BBB_2"] == "low_prior_guidance_confidence"


def test_management_guidance_bridge_writes_failures_and_validator(tmp_path: Path):
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
            },
        ]
    )
    features_path = tmp_path / "features.csv"
    out_path = tmp_path / "bridge.csv"
    failures_path = tmp_path / "failures.csv"
    features.to_csv(features_path, index=False)

    build_management_guidance_bridge(features_path, out_path, failures_path=failures_path)
    failures = pd.read_csv(failures_path)
    report = validate_management_guidance_bridge(out_path, min_ready_rows=1, preferred_ready_rows=1, min_tickers=1, max_single_ticker_share=1.0)

    assert set(failures["bridge_status"]) == {"missing_actual_revenue"}
    assert report["checks"]["no_eps_dependency"]
    assert report["checks"]["prior_event_gap_bounds"]
    assert report["checks"]["period_alignment_non_ambiguous"]
