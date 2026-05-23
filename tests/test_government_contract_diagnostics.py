from __future__ import annotations

import pandas as pd

from mre.government_contract_diagnostics import (
    build_government_contract_small_mid_diagnostics,
    run_government_contract_small_mid_material_diagnostic,
)


def _event_row(i: int, ticker: str, materiality: float, h1: float, *, small_mid: bool = True, agency: str = "DoD"):
    return {
        "event_id": f"E{i}",
        "ticker": ticker,
        "event_status": "ok",
        "small_mid_cap_flag": small_mid,
        "small_cap_flag": small_mid,
        "large_prime_flag": not small_mid,
        "large_prime_low_materiality_flag": not small_mid and materiality < 0.01,
        "actual_funded_award_flag": True,
        "duplicate_status": "primary",
        "obligated_amount_pct_market_cap": materiality,
        "award_amount_pct_market_cap": materiality,
        "agency": agency,
        "product_or_service_description": f"Program {i % 3}",
        "car_market_model_simple_h1": h1,
        "car_market_model_simple_h3": h1 + 0.005,
        "car_market_model_simple_h10": h1 + 0.010,
    }


def test_small_mid_diagnostics_reports_concentration_and_controls():
    rows = []
    tickers = ["KTOS", "AVAV", "MRCY", "RKLB", "RDW", "PL"]
    for i in range(36):
        rows.append(_event_row(i, tickers[i % len(tickers)], 0.012, 0.01 if i % 2 == 0 else -0.002))
    for i in range(10):
        rows.append(_event_row(100 + i, "LMT", 0.001, -0.001, small_mid=False))

    summary, leave_one, outliers, controls, decision = build_government_contract_small_mid_diagnostics(
        pd.DataFrame(rows),
        placebo_random_event_study=pd.DataFrame([_event_row(200 + i, "KTOS", 0.012, 0.0) for i in range(5)]),
        placebo_shifted_event_study=pd.DataFrame([_event_row(300 + i, "KTOS", 0.012, -0.001) for i in range(5)]),
        peer_event_study=pd.DataFrame([_event_row(400 + i, "AVAV", 0.012, 0.001) for i in range(5)]),
    )

    one_pct = summary[summary["threshold"].eq(0.01)].iloc[0]
    assert one_pct["ok_rows"] == 36
    assert one_pct["ticker_count"] == 6
    assert one_pct["top_ticker_share"] <= 0.35
    assert not leave_one.empty
    assert set(outliers["horizon"]) == {1, 3, 10}
    assert {"large_prime_low_materiality", "random_placebo", "shifted_placebo", "peer_control"}.issubset(set(controls["label"]))
    assert decision["decision"] in {
        "narrow slice deserves fresh-data buildout",
        "underpowered but interesting",
        "failed / freeze government contracts",
    }


def test_small_mid_diagnostic_runner_writes_artifacts(tmp_path):
    events = pd.DataFrame([_event_row(i, "KTOS" if i % 2 else "AVAV", 0.02, 0.01) for i in range(8)])
    event_path = tmp_path / "events.csv"
    events.to_csv(event_path, index=False)
    control_path = tmp_path / "control.csv"
    pd.DataFrame([_event_row(100 + i, "LMT", 0.001, -0.001, small_mid=False) for i in range(4)]).to_csv(control_path, index=False)

    report = run_government_contract_small_mid_material_diagnostic(
        event_study_path=event_path,
        placebo_random_event_study_path=control_path,
        placebo_shifted_event_study_path=control_path,
        peer_event_study_path=control_path,
        out_dir=tmp_path / "artifacts",
    )

    assert report["decision"] == "failed / freeze government contracts"
    out = tmp_path / "artifacts"
    assert (out / "government_contract_small_mid_material_diagnostic.csv").exists()
    assert (out / "government_contract_small_mid_leave_one_ticker_out.csv").exists()
    assert (out / "government_contract_small_mid_outlier_trim.csv").exists()
    assert (out / "government_contract_small_mid_controls.csv").exists()
    assert (out / "government_contract_agent_4h_report.md").exists()
