from __future__ import annotations

from math import exp
from pathlib import Path
from typing import Iterable

import pandas as pd

from .paths import ensure_dir, ensure_parent


GOVERNMENT_CONTRACT_4H_DECISIONS = {
    "narrow slice deserves fresh-data buildout",
    "underpowered but interesting",
    "failed / freeze government contracts",
}

DEFAULT_THRESHOLDS = (0.005, 0.01, 0.02, 0.05)
DEFAULT_HORIZONS = (1, 3, 10)
LARGE_PRIME_TICKERS = {"LMT", "RTX", "NOC", "GD", "BA", "HII", "LHX"}


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _truthy_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    return df[column].map(_truthy)


def _num_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="Float64")
    return pd.to_numeric(df[column], errors="coerce")


def _clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "nat"} else text


def _simple_return(frame: pd.DataFrame, horizon: int) -> pd.Series:
    simple_col = f"car_market_model_simple_h{horizon}"
    log_col = f"car_market_model_h{horizon}"
    if simple_col in frame.columns:
        return pd.to_numeric(frame[simple_col], errors="coerce")
    values = pd.to_numeric(frame.get(log_col, pd.Series(dtype=float)), errors="coerce")
    return values.map(lambda x: exp(float(x)) - 1.0 if pd.notna(x) else pd.NA)


def _event_ok(frame: pd.DataFrame) -> pd.DataFrame:
    if "event_status" not in frame.columns:
        return frame.copy()
    return frame[frame["event_status"].fillna("").astype(str).str.lower().eq("ok")].copy()


def _prepare_event_study(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    obligated = _num_series(out, "obligated_amount_pct_market_cap")
    award = _num_series(out, "award_amount_pct_market_cap")
    out["materiality_pct_market_cap"] = pd.concat([obligated, award], axis=1).max(axis=1)
    size_bucket = out.get("company_size_bucket", pd.Series("", index=out.index)).fillna("").astype(str).str.lower()
    large_prime = _truthy_series(out, "large_prime_flag") | out.get("ticker", pd.Series("", index=out.index)).fillna("").astype(str).str.upper().isin(LARGE_PRIME_TICKERS)
    out["diagnostic_small_mid_flag"] = (
        _truthy_series(out, "small_mid_cap_flag")
        | _truthy_series(out, "small_cap_flag")
        | size_bucket.isin({"micro_cap", "small_cap", "mid_cap", "small_300m_2b", "mid_2b_10b"})
    ) & ~large_prime
    out["diagnostic_actual_funded_flag"] = _truthy_series(out, "actual_funded_award_flag")
    out["diagnostic_primary_duplicate_flag"] = out.get("duplicate_status", pd.Series("", index=out.index)).fillna("").astype(str).str.lower().eq("primary")
    out["diagnostic_large_prime_low_materiality_flag"] = _truthy_series(out, "large_prime_low_materiality_flag") | (large_prime & out["materiality_pct_market_cap"].lt(0.01))
    return out


def _top_count(frame: pd.DataFrame, column: str) -> tuple[str, int, float]:
    if column not in frame.columns or frame.empty:
        return "", 0, 0.0
    counts = frame[column].map(_clean_text)
    counts = counts[counts.ne("")]
    if counts.empty:
        return "", 0, 0.0
    top_value = counts.value_counts().sort_values(ascending=False).index[0]
    top_count = int((counts == top_value).sum())
    return top_value, top_count, top_count / len(frame) if len(frame) else 0.0


def _summary_row(
    frame: pd.DataFrame,
    *,
    label: str,
    threshold: float | None,
    horizons: Iterable[int],
) -> dict[str, object]:
    ok = _event_ok(frame)
    tickers = ok.get("ticker", pd.Series(dtype=object)).map(_clean_text)
    ticker_counts = tickers[tickers.ne("")].value_counts()
    top_ticker = ticker_counts.index[0] if len(ticker_counts) else ""
    top_ticker_count = int(ticker_counts.iloc[0]) if len(ticker_counts) else 0
    agency, agency_count, agency_share = _top_count(ok, "agency")
    program, program_count, program_share = _top_count(ok, "product_or_service_description")
    materiality = pd.to_numeric(ok.get("materiality_pct_market_cap", pd.Series(dtype=float)), errors="coerce")

    row: dict[str, object] = {
        "label": label,
        "threshold": threshold,
        "rows": int(len(frame)),
        "ok_rows": int(len(ok)),
        "ticker_count": int(tickers[tickers.ne("")].nunique()),
        "top_ticker": top_ticker,
        "top_ticker_count": top_ticker_count,
        "top_ticker_share": top_ticker_count / len(ok) if len(ok) else 0.0,
        "top_agency": agency,
        "top_agency_count": agency_count,
        "top_agency_share": agency_share,
        "top_program": program,
        "top_program_count": program_count,
        "top_program_share": program_share,
        "median_materiality_pct_market_cap": float(materiality.median()) if materiality.notna().any() else None,
        "max_materiality_pct_market_cap": float(materiality.max()) if materiality.notna().any() else None,
    }
    for horizon in horizons:
        returns = _simple_return(ok, horizon).dropna().astype(float)
        row[f"h{horizon}_n"] = int(len(returns))
        row[f"h{horizon}_mean_simple"] = float(returns.mean()) if len(returns) else None
        row[f"h{horizon}_median_simple"] = float(returns.median()) if len(returns) else None
        row[f"h{horizon}_positive_rate"] = float((returns > 0).mean()) if len(returns) else None
        row[f"h{horizon}_sign_accuracy"] = float((returns > 0).mean()) if len(returns) else None
    return row


def _small_mid_material_slice(events: pd.DataFrame, threshold: float) -> pd.DataFrame:
    return events[
        events["diagnostic_small_mid_flag"]
        & events["diagnostic_actual_funded_flag"]
        & events["diagnostic_primary_duplicate_flag"]
        & events["materiality_pct_market_cap"].ge(threshold)
    ].copy()


def build_government_contract_small_mid_diagnostics(
    event_study: str | Path | pd.DataFrame,
    *,
    placebo_random_event_study: str | Path | pd.DataFrame | None = None,
    placebo_shifted_event_study: str | Path | pd.DataFrame | None = None,
    peer_event_study: str | Path | pd.DataFrame | None = None,
    thresholds: Iterable[float] = DEFAULT_THRESHOLDS,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """Build Agent 4H narrow small/mid material-award diagnostics without a new model."""
    raw = pd.read_csv(event_study) if not isinstance(event_study, pd.DataFrame) else event_study.copy()
    events = _prepare_event_study(raw)
    thresholds = tuple(float(t) for t in thresholds)
    horizons = tuple(int(h) for h in horizons)

    summary_rows: list[dict[str, object]] = []
    leave_one_rows: list[dict[str, object]] = []
    outlier_rows: list[dict[str, object]] = []

    for threshold in thresholds:
        slice_df = _small_mid_material_slice(events, threshold)
        summary_rows.append(_summary_row(slice_df, label="small_mid_material", threshold=threshold, horizons=horizons))

        tickers = sorted(slice_df.get("ticker", pd.Series(dtype=object)).map(_clean_text).dropna().unique())
        for ticker in tickers:
            if not ticker:
                continue
            remaining = slice_df[slice_df["ticker"].map(_clean_text) != ticker].copy()
            row = _summary_row(remaining, label="leave_one_ticker_out", threshold=threshold, horizons=horizons)
            row["removed_ticker"] = ticker
            row["removed_rows"] = int((slice_df["ticker"].map(_clean_text) == ticker).sum())
            leave_one_rows.append(row)

        ok = _event_ok(slice_df)
        for horizon in horizons:
            returns = _simple_return(ok, horizon).dropna().astype(float)
            if returns.empty:
                trimmed = ok.iloc[0:0].copy()
                removed_ids = ""
            else:
                remove_index = returns.abs().sort_values(ascending=False).head(3).index
                trimmed = ok.drop(index=remove_index)
                removed_ids = ";".join(ok.loc[remove_index, "event_id"].map(_clean_text)) if "event_id" in ok.columns else ";".join(map(str, remove_index))
            ret = _simple_return(trimmed, horizon).dropna().astype(float)
            outlier_rows.append(
                {
                    "threshold": threshold,
                    "horizon": horizon,
                    "original_rows": int(len(ok)),
                    "trimmed_rows": int(len(trimmed)),
                    "removed_top3_abs_return_event_ids": removed_ids,
                    "trimmed_mean_simple": float(ret.mean()) if len(ret) else None,
                    "trimmed_median_simple": float(ret.median()) if len(ret) else None,
                    "trimmed_positive_rate": float((ret > 0).mean()) if len(ret) else None,
                }
            )

    control_rows: list[dict[str, object]] = []
    large_prime = events[events["diagnostic_large_prime_low_materiality_flag"]].copy()
    control_rows.append(_summary_row(large_prime, label="large_prime_low_materiality", threshold=None, horizons=horizons))
    control_sources = [
        ("random_placebo", placebo_random_event_study),
        ("shifted_placebo", placebo_shifted_event_study),
        ("peer_control", peer_event_study),
    ]
    for label, source in control_sources:
        if source is None:
            continue
        frame = pd.read_csv(source) if not isinstance(source, pd.DataFrame) else source.copy()
        control_rows.append(_summary_row(_prepare_event_study(frame), label=label, threshold=None, horizons=horizons))

    summaries = pd.DataFrame(summary_rows)
    leave_one = pd.DataFrame(leave_one_rows)
    outliers = pd.DataFrame(outlier_rows)
    controls = pd.DataFrame(control_rows)
    decision = _diagnostic_decision(summaries, leave_one, outliers, controls)
    return summaries, leave_one, outliers, controls, decision


def _diagnostic_decision(
    summaries: pd.DataFrame,
    leave_one: pd.DataFrame,
    outliers: pd.DataFrame,
    controls: pd.DataFrame,
) -> dict[str, object]:
    structural = summaries[
        summaries["ok_rows"].ge(30)
        & summaries["ticker_count"].ge(6)
        & summaries["top_ticker_share"].le(0.35)
    ].copy()
    if structural.empty:
        return {
            "decision": "failed / freeze government contracts",
            "primary_reason": "No pre-registered small/mid material threshold reached 30 usable rows, 6+ tickers, and top ticker share <= 35%.",
            "structural_thresholds_passing": 0,
        }

    robust_thresholds: list[float] = []
    for _, row in structural.iterrows():
        threshold = float(row["threshold"])
        loo = leave_one[leave_one["threshold"].eq(threshold)]
        trims = outliers[outliers["threshold"].eq(threshold)]
        h1_loo_min = pd.to_numeric(loo.get("h1_median_simple", pd.Series(dtype=float)), errors="coerce").min()
        h1_trim = pd.to_numeric(trims[trims["horizon"].eq(1)].get("trimmed_median_simple", pd.Series(dtype=float)), errors="coerce")
        if pd.notna(h1_loo_min) and h1_loo_min > 0 and len(h1_trim) and h1_trim.iloc[0] > 0:
            robust_thresholds.append(threshold)

    if robust_thresholds and summaries["ok_rows"].max() >= 40:
        decision = "narrow slice deserves fresh-data buildout"
        reason = "At least one structural threshold remained positive under leave-one-ticker and top-3 outlier diagnostics."
    elif robust_thresholds:
        decision = "underpowered but interesting"
        reason = "A structural threshold was directionally robust, but usable row count remains below the preferred 40-row floor."
    else:
        decision = "failed / freeze government contracts"
        reason = "Structural counts passed, but robustness weakened under leave-one-ticker or top-3 outlier removal."

    return {
        "decision": decision,
        "primary_reason": reason,
        "structural_thresholds_passing": int(len(structural)),
        "robust_thresholds": robust_thresholds,
    }


def write_government_contract_4h_report(
    path: str | Path,
    *,
    summaries: pd.DataFrame,
    leave_one: pd.DataFrame,
    outliers: pd.DataFrame,
    controls: pd.DataFrame,
    decision: dict[str, object],
) -> Path:
    lines: list[str] = [
        "# Agent 4H Government Contract Small/Mid Material Award Diagnostic",
        "",
        f"Decision: {decision.get('decision')}.",
        "",
        "This is a narrow diagnostic only. It does not run a new broad model and does not graduate a signal.",
        "",
        "## Structural Thresholds",
        "",
        "| threshold | rows | tickers | top ticker | top ticker share | top agency share | top program share | h1 median | h1 sign accuracy | h3 median | h10 median |",
        "|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in summaries.iterrows():
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{float(row['threshold']):.3f}",
                    str(int(row.get("ok_rows", 0))),
                    str(int(row.get("ticker_count", 0))),
                    _clean_text(row.get("top_ticker")),
                    f"{float(row.get('top_ticker_share', 0.0)):.3f}",
                    f"{float(row.get('top_agency_share', 0.0)):.3f}",
                    f"{float(row.get('top_program_share', 0.0)):.3f}",
                    _fmt(row.get("h1_median_simple")),
                    _fmt(row.get("h1_sign_accuracy")),
                    _fmt(row.get("h3_median_simple")),
                    _fmt(row.get("h10_median_simple")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Controls",
            "",
            "| control | rows | tickers | h1 median | h1 sign accuracy | h3 median | h10 median |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for _, row in controls.iterrows():
        lines.append(
            "| "
            + " | ".join(
                [
                    _clean_text(row.get("label")),
                    str(int(row.get("ok_rows", 0))),
                    str(int(row.get("ticker_count", 0))),
                    _fmt(row.get("h1_median_simple")),
                    _fmt(row.get("h1_sign_accuracy")),
                    _fmt(row.get("h3_median_simple")),
                    _fmt(row.get("h10_median_simple")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Robustness",
            "",
            f"- leave-one-ticker rows: {len(leave_one)}",
            f"- top-3 outlier trim rows: {len(outliers)}",
            f"- structural thresholds passing count/ticker/concentration gate: {decision.get('structural_thresholds_passing')}",
            f"- robust thresholds: {decision.get('robust_thresholds') or []}",
            f"- primary reason: {decision.get('primary_reason')}",
            "",
            "## Required Cautions",
            "",
            "- Thresholds are the pre-registered 0.5%, 1%, 2%, and 5% market-cap cuts.",
            "- This diagnostic does not tune thresholds based on returns.",
            "- Broad government-contract awards already failed Agent 4G falsification.",
            "- A positive descriptive slice is not a tradable signal without a fresh separately pre-registered corpus expansion.",
        ]
    )
    p = ensure_parent(path)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _fmt(value: object) -> str:
    try:
        if value is None or pd.isna(value):
            return ""
        return f"{float(value):.4f}"
    except Exception:
        return ""


def run_government_contract_small_mid_material_diagnostic(
    *,
    event_study_path: str | Path = "artifacts/government_contract_event_study.csv",
    placebo_random_event_study_path: str | Path = "artifacts/government_contract_placebo_random_event_study.csv",
    placebo_shifted_event_study_path: str | Path = "artifacts/government_contract_placebo_shifted_event_study.csv",
    peer_event_study_path: str | Path = "artifacts/government_contract_peer_event_study.csv",
    out_dir: str | Path = "artifacts",
    thresholds: Iterable[float] = DEFAULT_THRESHOLDS,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> dict[str, object]:
    out_root = ensure_dir(out_dir)
    summaries, leave_one, outliers, controls, decision = build_government_contract_small_mid_diagnostics(
        event_study_path,
        placebo_random_event_study=placebo_random_event_study_path,
        placebo_shifted_event_study=placebo_shifted_event_study_path,
        peer_event_study=peer_event_study_path,
        thresholds=thresholds,
        horizons=horizons,
    )

    summary_path = out_root / "government_contract_small_mid_material_diagnostic.csv"
    leave_one_path = out_root / "government_contract_small_mid_leave_one_ticker_out.csv"
    outlier_path = out_root / "government_contract_small_mid_outlier_trim.csv"
    controls_path = out_root / "government_contract_small_mid_controls.csv"
    report_path = out_root / "government_contract_agent_4h_report.md"
    summaries.to_csv(summary_path, index=False)
    leave_one.to_csv(leave_one_path, index=False)
    outliers.to_csv(outlier_path, index=False)
    controls.to_csv(controls_path, index=False)
    write_government_contract_4h_report(
        report_path,
        summaries=summaries,
        leave_one=leave_one,
        outliers=outliers,
        controls=controls,
        decision=decision,
    )

    return {
        "agent": "4H",
        "domain": "government_contract_awards",
        "decision": decision["decision"],
        "primary_reason": decision["primary_reason"],
        "summary_rows": int(len(summaries)),
        "leave_one_rows": int(len(leave_one)),
        "outlier_rows": int(len(outliers)),
        "control_rows": int(len(controls)),
        "artifacts": {
            "summary": str(summary_path),
            "leave_one_ticker_out": str(leave_one_path),
            "outlier_trim": str(outlier_path),
            "controls": str(controls_path),
            "agent_report": str(report_path),
        },
    }
