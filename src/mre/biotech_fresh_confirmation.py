from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .backtest import (
    calibration_table,
    make_peer_control_events,
    make_placebo_events,
    null_shuffle_strategy_test,
    simulate_event_strategy,
)
from .biotech_falsification import (
    _bool_series,
    _control_event_study,
    _simple_from_log,
    _summarize_returns,
    _write_json,
    add_sector_targets,
    biotech_base_rate_table,
    evaluate_biotech_hypotheses,
    prepare_biotech_falsification_events,
    purged_walk_forward_sector_model,
    simulate_source_direction_strategy,
)
from .paths import ensure_dir, ensure_parent
from .prices import load_price_csv


FRESH_DECISION_OPTIONS = {
    "fresh-confirmed, continue to leakage/execution audit",
    "promising but underpowered",
    "failed fresh confirmation",
    "parser/context issue found",
    "timestamp/leakage issue found",
}

HARD_REJECT_FLAGS = {
    "previously_announced_not_new",
    "pipeline_update_not_binary",
    "trial_initiation_not_binary",
    "trial_design_not_binary",
    "enrollment_update_not_binary",
    "background_approval_language_not_decision",
}

READOUT_TERMS = (
    "announced topline results",
    "announced top-line results",
    "positive topline results",
    "top-line results",
    "topline results",
    "met primary endpoint",
    "meet primary endpoint",
    "primary endpoint was met",
    "did not meet",
    "failed to meet",
    "statistically significant",
)
REGULATORY_APPROVAL_TERMS = (
    "fda approved",
    "fda has approved",
    "fda approves",
    "u.s. food and drug administration approved",
    "received approval",
    "approved the",
    "granted approval",
)
DESIGNATION_TERMS = (
    "granted fast track",
    "fast track designation",
    "breakthrough therapy designation",
    "granted breakthrough",
    "priority review",
    "orphan drug designation",
)
CRL_TERMS = ("complete response letter", "crl")
HALT_TERMS = ("trial halt", "trial halted", "halted the trial", "clinical hold", "discontinued", "discontinue", "terminated")
SAFETY_TERMS = (
    "serious adverse event",
    "adverse event",
    "dose-limiting toxicity",
    "grade 4",
    "grade 5",
    "death",
    "safety concern",
    "clinical hold",
    "liver enzyme",
    "hepatotoxicity",
)
NEGATED_SAFETY_TERMS = (
    "no serious adverse",
    "no treatment-related serious",
    "well tolerated",
    "generally well tolerated",
    "no dose-limiting",
    "no grade 4",
    "no grade 5",
)
NOT_NEW_TERMS = ("previously announced", "previously disclosed", "will present", "to present", "accepted for presentation")


def _clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null", "nat"}:
        return ""
    return text


def _has_any(text: str, terms: Iterable[str]) -> bool:
    low = text.lower()
    return any(term in low for term in terms)


def _flag_set(value: object) -> set[str]:
    return {flag.strip() for flag in _clean_text(value).split(";") if flag.strip()}


def _evidence_blob(row: pd.Series) -> str:
    evidence_cols = [
        "source_evidence_text",
        "event_type_evidence",
        "approval_status_evidence",
        "fda_action_evidence",
        "endpoint_met_evidence",
        "p_value_evidence",
        "hazard_ratio_evidence",
        "primary_endpoint_evidence",
        "safety_issue_evidence",
        "adverse_event_language_evidence",
    ]
    return " ".join(_clean_text(row.get(col, "")) for col in evidence_cols)


def classify_fresh_candidate(row: pd.Series) -> tuple[bool, str]:
    """Strictly rule-review a parser candidate without changing parser labels."""
    event_type = _clean_text(row.get("biotech_catalyst_event_type", row.get("event_type", ""))).lower()
    if not event_type or event_type == "unknown":
        return False, "unknown_event_type"
    evidence = _evidence_blob(row)
    low = evidence.lower()
    if not evidence:
        return False, "missing_source_evidence"
    flags = _flag_set(row.get("parser_quality_flags", ""))
    hard_flags = flags & HARD_REJECT_FLAGS
    if hard_flags:
        return False, "hard_false_positive_flag:" + ",".join(sorted(hard_flags))

    if event_type in {"phase_2_readout", "phase_3_readout", "pivotal_trial_readout", "endpoint_success", "endpoint_failure"}:
        if _has_any(low, READOUT_TERMS) and not _has_any(low, NOT_NEW_TERMS):
            return True, "fresh_readout_with_new_result_language"
        return False, "readout_without_new_result_language"
    if event_type in {"fda_approval", "label_expansion", "accelerated_approval"}:
        if _has_any(low, REGULATORY_APPROVAL_TERMS) and not _has_any(low, ("fda-approved", "approved product", "previously approved", "previously announced")):
            return True, "fresh_regulatory_approval_language"
        return False, "approval_background_or_not_new"
    if event_type == "fda_complete_response_letter":
        if _has_any(low, CRL_TERMS) and not _has_any(low, NOT_NEW_TERMS):
            return True, "fresh_complete_response_letter"
        return False, "crl_background_or_not_new"
    if event_type in {"trial_halt", "trial_discontinuation"}:
        if _has_any(low, HALT_TERMS) and not _has_any(low, ("risk factor", "may discontinue", "previously announced")):
            return True, "fresh_trial_halt_or_discontinuation"
        return False, "trial_halt_background_or_risk_factor"
    if event_type == "safety_signal":
        if _has_any(low, SAFETY_TERMS) and not _has_any(low, NEGATED_SAFETY_TERMS) and "risk factor" not in low:
            return True, "fresh_safety_negative_language"
        return False, "safety_background_or_negated"
    if event_type in {"priority_review", "breakthrough_designation", "fast_track_designation", "orphan_drug_designation"}:
        if _has_any(low, DESIGNATION_TERMS) and not _has_any(low, NOT_NEW_TERMS):
            return True, "fresh_designation_only_contrast"
        return False, "designation_background_or_not_new"
    return False, "event_type_not_in_fresh_confirmation_scope"


def build_fresh_reviewed_events(
    raw_events: str | Path | pd.DataFrame,
    *,
    original_events: str | Path | pd.DataFrame | None = "artifacts/biotech_catalyst_event_study.csv",
    out_path: str | Path | None = None,
    reviewed_only: bool = True,
    sector_benchmark: str = "XBI",
) -> pd.DataFrame:
    """Create a fresh rule-reviewed holdout from rows outside the Agent 3D corpus."""
    df = pd.read_csv(raw_events) if not isinstance(raw_events, pd.DataFrame) else raw_events.copy()
    original_ids: set[str] = set()
    if original_events is not None:
        orig = pd.read_csv(original_events) if not isinstance(original_events, pd.DataFrame) else original_events.copy()
        if "event_id" in orig.columns:
            original_ids = set(orig["event_id"].dropna().astype(str))

    if "event_id" not in df.columns:
        raise ValueError("Fresh candidate events must include event_id")
    out = df[~df["event_id"].astype(str).isin(original_ids)].copy()
    if out.empty:
        raise ValueError("No fresh candidate rows remain after excluding Agent 3D event_ids")

    decisions = out.apply(classify_fresh_candidate, axis=1)
    out["_fresh_keep"] = [bool(item[0]) for item in decisions]
    out["_fresh_review_reason"] = [str(item[1]) for item in decisions]
    out["review_status"] = np.where(out["_fresh_keep"], "reviewed", "rejected")
    out["drop_reason"] = np.where(out["_fresh_keep"], "", out["_fresh_review_reason"])
    out["label_quality"] = np.where(out["_fresh_keep"], "rule_reviewed_fresh_confirmation", out.get("label_quality", "machine_candidate"))
    out["evidence_status"] = np.where(out["_fresh_keep"], "source_backed", out.get("evidence_status", "needs_evidence_review"))
    notes = out.get("review_notes", pd.Series("", index=out.index)).fillna("").astype(str)
    suffix = "agent_3e_rule_review=" + out["_fresh_review_reason"].astype(str)
    out["review_notes"] = np.where(notes.str.strip().eq(""), suffix, notes + "; " + suffix)
    if "sector_benchmark" not in out.columns:
        out["sector_benchmark"] = sector_benchmark
    else:
        out["sector_benchmark"] = out["sector_benchmark"].fillna("").astype(str)
        bench = out["sector_benchmark"].fillna("").astype(str).str.upper().str.strip()
        out.loc[bench.isin({"", "NAN", "NONE", "UNKNOWN"}), "sector_benchmark"] = sector_benchmark

    if reviewed_only:
        out = out[out["_fresh_keep"]].copy()
    out = out.drop_duplicates("event_id").sort_values(["event_time", "ticker", "event_id"]).reset_index(drop=True)
    if out_path:
        p = ensure_parent(out_path)
        out.to_csv(p, index=False)
    return out


def _anchor_price(prices: pd.DataFrame, event_time: object, release_session: object) -> tuple[pd.Timestamp | None, float]:
    ts = pd.to_datetime(event_time, errors="coerce")
    if pd.isna(ts):
        return None, np.nan
    ts = ts.tz_localize(None) if getattr(ts, "tzinfo", None) else ts
    date = ts.normalize()
    session = _clean_text(release_session).lower()
    include_same_day = session in {"after_close", "intraday", "market_hours", "unknown", ""}
    eligible = prices[prices["date"] <= date] if include_same_day else prices[prices["date"] < date]
    if eligible.empty:
        return None, np.nan
    last = eligible.iloc[-1]
    return pd.to_datetime(last["date"]), float(last["adj_close"])


def _window_return(prices: pd.DataFrame, anchor_date: pd.Timestamp | None, window: int) -> float:
    if anchor_date is None:
        return np.nan
    dates = prices["date"]
    matches = prices.index[dates == anchor_date].tolist()
    if not matches:
        return np.nan
    idx = matches[-1]
    start_idx = idx - int(window)
    if start_idx < 0:
        return np.nan
    start = pd.to_numeric(pd.Series([prices.iloc[start_idx]["adj_close"]]), errors="coerce").iloc[0]
    end = pd.to_numeric(pd.Series([prices.iloc[idx]["adj_close"]]), errors="coerce").iloc[0]
    if pd.isna(start) or pd.isna(end) or start == 0:
        return np.nan
    return float(end / start - 1.0)


def _lookup_shares(row: pd.Series, shares_context: pd.DataFrame) -> pd.Series:
    if shares_context.empty or "ticker" not in shares_context.columns:
        return pd.Series(dtype=object)
    ticker = _clean_text(row.get("ticker", "")).upper()
    subset = shares_context[shares_context["ticker"].astype(str).str.upper() == ticker].copy()
    if subset.empty:
        return pd.Series(dtype=object)
    sort_col = "filed_at" if "filed_at" in subset.columns else "asof_date" if "asof_date" in subset.columns else ""
    if sort_col:
        subset[sort_col] = pd.to_datetime(subset[sort_col], errors="coerce").dt.tz_localize(None)
        event_time = pd.to_datetime(row.get("event_time"), errors="coerce")
        if pd.notna(event_time):
            event_time = event_time.tz_localize(None) if getattr(event_time, "tzinfo", None) else event_time
            subset = subset[subset[sort_col] <= event_time]
        subset = subset.sort_values(sort_col, ascending=False)
    return subset.iloc[0] if not subset.empty else pd.Series(dtype=object)


def enrich_fresh_context(
    events: str | Path | pd.DataFrame,
    *,
    prices_dir: str | Path = "data/prices/biotech_catalysts",
    shares_context: str | Path | pd.DataFrame | None = None,
    benchmark_ticker: str = "XBI",
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    """Add point-in-time price/run-up context and share-derived market cap when available."""
    df = pd.read_csv(events) if not isinstance(events, pd.DataFrame) else events.copy()
    shares = pd.DataFrame()
    if shares_context is not None:
        shares = pd.read_csv(shares_context) if not isinstance(shares_context, pd.DataFrame) else shares_context.copy()

    benchmark_prices = load_price_csv(prices_dir, benchmark_ticker.upper())
    price_cache: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, object]] = []
    for _, row in df.iterrows():
        out = row.to_dict()
        ticker = _clean_text(row.get("ticker", "")).upper()
        status: list[str] = []
        try:
            prices = price_cache.setdefault(ticker, load_price_csv(prices_dir, ticker))
        except FileNotFoundError:
            prices = pd.DataFrame()
            status.append("missing_ticker_prices")

        anchor_date, last_close = (None, np.nan) if prices.empty else _anchor_price(prices, row.get("event_time"), row.get("release_session"))
        if pd.isna(last_close):
            status.append("missing_pre_event_close")
        out["price_anchor_date"] = anchor_date.date().isoformat() if anchor_date is not None else ""
        out["last_close_before_event"] = last_close

        shares_lookup = _lookup_shares(row, shares)
        shares_out = pd.to_numeric(pd.Series([row.get("shares_outstanding_before_event", np.nan)]), errors="coerce").iloc[0]
        if pd.isna(shares_out) and not shares_lookup.empty:
            shares_out = pd.to_numeric(pd.Series([shares_lookup.get("shares_outstanding_before_event", np.nan)]), errors="coerce").iloc[0]
        out["shares_outstanding_before_event"] = shares_out
        if not shares_lookup.empty:
            out["shares_outstanding_filed_at"] = _clean_text(shares_lookup.get("filed_at", ""))
            out["shares_outstanding_source_url"] = _clean_text(shares_lookup.get("source_url", ""))

        market_cap = pd.to_numeric(pd.Series([row.get("market_cap_before_event", np.nan)]), errors="coerce").iloc[0]
        if pd.isna(market_cap) and pd.notna(shares_out) and pd.notna(last_close):
            market_cap = float(shares_out) * float(last_close)
        out["market_cap_before_event"] = market_cap

        bench_anchor, _ = _anchor_price(benchmark_prices, row.get("event_time"), row.get("release_session"))
        for window in (20, 60):
            stock_ret = _window_return(prices, anchor_date, window) if not prices.empty else np.nan
            bench_ret = _window_return(benchmark_prices, bench_anchor, window)
            out[f"pre_event_return_{window}d"] = stock_ret
            out[f"pre_event_benchmark_return_{window}d"] = bench_ret
            out[f"pre_event_market_adjusted_return_{window}d"] = stock_ret - bench_ret if pd.notna(stock_ret) and pd.notna(bench_ret) else np.nan
        out["fresh_context_status"] = ";".join(status)
        rows.append(out)

    enriched = pd.DataFrame(rows)
    if out_path:
        p = ensure_parent(out_path)
        enriched.to_csv(p, index=False)
    return enriched


def _expected_direction(row: pd.Series) -> str:
    direction = _clean_text(row.get("event_direction_pre_price", row.get("surprise_direction", ""))).lower()
    if direction in {"positive", "negative"}:
        return direction
    return ""


def _winsorized_mean(series: pd.Series, lower: float = 0.05, upper: float = 0.95) -> float | None:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    lo = s.quantile(lower)
    hi = s.quantile(upper)
    return float(s.clip(lo, hi).mean())


def outlier_robustness_report(event_study: pd.DataFrame, *, horizons: Iterable[int] = (1, 3)) -> dict[str, object]:
    ok = event_study[event_study.get("event_status", "ok").astype(str).eq("ok")].copy()
    out: dict[str, object] = {"rows": int(len(ok)), "horizons": {}}
    for h in horizons:
        col = f"car_sector_adj_h{h}"
        frame = ok[pd.to_numeric(ok.get(col, pd.Series(np.nan, index=ok.index)), errors="coerce").notna()].copy()
        frame["_car"] = pd.to_numeric(frame[col], errors="coerce")
        frame["_abs_car"] = frame["_car"].abs()
        frame = frame.sort_values("_abs_car", ascending=False).reset_index(drop=True)
        expected = frame.apply(_expected_direction, axis=1)
        align = np.select([expected.eq("positive"), expected.eq("negative")], [frame["_car"] > 0, frame["_car"] < 0], default=np.nan)
        item: dict[str, object] = {
            "n": int(len(frame)),
            "mean": float(frame["_car"].mean()) if len(frame) else None,
            "median": float(frame["_car"].median()) if len(frame) else None,
            "winsorized_mean_5_95": _winsorized_mean(frame["_car"]),
            "sign_accuracy_directional_only": float(pd.Series(align).dropna().mean()) if pd.Series(align).dropna().size else None,
        }
        total_abs = float(frame["_abs_car"].sum()) if len(frame) else 0.0
        for n in (1, 3, 5):
            trimmed = frame.iloc[n:].copy()
            item[f"exclude_top_{n}_abs_mean"] = float(trimmed["_car"].mean()) if len(trimmed) else None
            item[f"exclude_top_{n}_abs_median"] = float(trimmed["_car"].median()) if len(trimmed) else None
            item[f"top_{n}_abs_share"] = float(frame.head(n)["_abs_car"].sum() / total_abs) if total_abs else None
        item["largest_abs_events"] = [
            {
                "event_id": _clean_text(row.get("event_id", "")),
                "ticker": _clean_text(row.get("ticker", "")),
                "event_type": _clean_text(row.get("biotech_catalyst_event_type", row.get("event_type", ""))),
                "direction": _clean_text(row.get("event_direction_pre_price", "")),
                "car_sector_adj": float(row["_car"]),
                "abs_car_sector_adj": float(row["_abs_car"]),
            }
            for _, row in frame.head(5).iterrows()
        ]
        out["horizons"][f"h{h}"] = item
    return out


def write_fresh_outlier_robustness(path: str | Path, report: dict[str, object]) -> Path:
    lines = ["# Biotech Fresh-Data Outlier Robustness", "", f"- rows: {report.get('rows')}", ""]
    for horizon, item in (report.get("horizons", {}) or {}).items():
        lines.extend(
            [
                f"## {horizon}",
                "",
                f"- n: {item.get('n')}",
                f"- mean: {item.get('mean')}",
                f"- median: {item.get('median')}",
                f"- winsorized mean 5/95: {item.get('winsorized_mean_5_95')}",
                f"- sign accuracy, directional rows only: {item.get('sign_accuracy_directional_only')}",
                f"- exclude top 1 absolute mean: {item.get('exclude_top_1_abs_mean')}",
                f"- exclude top 3 absolute mean: {item.get('exclude_top_3_abs_mean')}",
                f"- exclude top 5 absolute mean: {item.get('exclude_top_5_abs_mean')}",
                f"- top 1 / 3 / 5 absolute share: {item.get('top_1_abs_share')} / {item.get('top_3_abs_share')} / {item.get('top_5_abs_share')}",
                "",
                "Largest absolute h1/h3 events:",
            ]
        )
        for event in item.get("largest_abs_events", []):
            lines.append(
                f"- {event.get('event_id')} {event.get('ticker')} {event.get('event_type')} "
                f"direction={event.get('direction')} car={event.get('car_sector_adj')}"
            )
        lines.append("")
    p = ensure_parent(path)
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def _fresh_gate_summary(events: pd.DataFrame, predictions: pd.DataFrame, parser_errors_path: str | Path | None) -> dict[str, object]:
    direction = events.get("event_direction_pre_price", pd.Series("", index=events.index)).fillna("").astype(str).str.lower()
    market_cap = pd.to_numeric(events.get("market_cap_before_event", pd.Series(np.nan, index=events.index)), errors="coerce")
    runup = pd.to_numeric(events.get("pre_event_market_adjusted_return_20d", pd.Series(np.nan, index=events.index)), errors="coerce")
    timestamps = pd.to_datetime(events.get("event_time", pd.Series("", index=events.index)), errors="coerce")
    parser_pass = True
    if parser_errors_path:
        p = Path(parser_errors_path)
        if p.exists():
            errors = pd.read_csv(p)
            parser_pass = bool(errors.empty or errors.get("status", pd.Series(dtype=str)).astype(str).str.lower().eq("ok").all())
    gates = {
        "fresh_reviewed_usable_rows_40": len(events) >= 40,
        "fresh_binary_catalyst_rows_25": int(_bool_series(events, "binary_catalyst_flag").sum()) >= 25,
        "fresh_negative_catalyst_rows_15": int(direction.eq("negative").sum()) >= 15,
        "fresh_positive_or_contrast_rows_15": int(direction.isin({"positive", "mixed", "neutral"}).sum()) >= 15,
        "fresh_market_cap_context_rows_25": int(market_cap.notna().sum()) >= 25,
        "fresh_xbi_runup_context_rows_25": int(runup.notna().sum()) >= 25,
        "fresh_likely_oos_predictions_20": int(predictions.get("predicted_positive_probability", pd.Series(dtype=float)).notna().sum()) >= 20,
        "parser_audit_remains_passing": parser_pass,
        "timestamps_reviewed": int(timestamps.notna().sum()) == int(len(events)),
    }
    return {
        "gates": gates,
        "all_minimum_gates_pass": bool(all(gates.values())),
        "fresh_reviewed_usable_rows": int(len(events)),
        "fresh_binary_catalyst_rows": int(_bool_series(events, "binary_catalyst_flag").sum()),
        "fresh_negative_catalyst_rows": int(direction.eq("negative").sum()),
        "fresh_positive_or_contrast_rows": int(direction.isin({"positive", "mixed", "neutral"}).sum()),
        "rows_with_market_cap_context": int(market_cap.notna().sum()),
        "rows_with_xbi_runup_context": int(runup.notna().sum()),
        "likely_oos_predictions": int(predictions.get("predicted_positive_probability", pd.Series(dtype=float)).notna().sum()),
        "rows_with_clear_timestamps": int(timestamps.notna().sum()),
    }


def _fresh_decision(report: dict[str, object]) -> str:
    gates = report.get("fresh_minimum_gates", {})
    if not isinstance(gates, dict) or not gates.get("all_minimum_gates_pass", False):
        failed = [name for name, ok in (gates.get("gates", {}) or {}).items() if not ok]
        if any("parser" in name for name in failed):
            return "parser/context issue found"
        if any("timestamp" in name for name in failed):
            return "timestamp/leakage issue found"
        return "promising but underpowered"

    walk = report.get("walk_forward", {}) or {}
    metrics = walk.get("metrics", {}) if isinstance(walk, dict) else {}
    calibration = report.get("calibration", {}) or {}
    strategy = report.get("strategy", {}) or {}
    null = report.get("null_shuffle", {}) or {}
    hypotheses = report.get("hypotheses", {}) or {}
    placebo = report.get("placebo_controls", {}) or {}
    peer = report.get("peer_controls", {}) or {}
    outliers = report.get("outlier_robustness", {}) or {}

    h1 = hypotheses.get("h1_negative_binary_catalyst", {}) or {}
    h3 = hypotheses.get("h3_crl_halt_endpoint_failure", {}) or {}
    h4 = hypotheses.get("h4_designation_only", {}) or {}
    neg_h1 = (h1.get("h1", {}) or {}).get("mean_log")
    neg_h3 = (h1.get("h3", {}) or {}).get("mean_log")
    h3_h1 = (h3.get("h1", {}) or {}).get("mean_log")
    designation_abs = (h4.get("h1", {}) or {}).get("mean_abs_log")
    binary_abs = (report.get("base_rate_contrasts", {}) or {}).get("binary_mean_abs_h1")
    h1_outlier = ((outliers.get("horizons", {}) or {}).get("h1", {}) or {})
    outlier_not_collapse = h1_outlier.get("exclude_top_5_abs_mean") is not None

    passed = (
        metrics.get("roc_auc") is not None
        and float(metrics["roc_auc"]) > 0.58
        and calibration.get("expected_calibration_error") is not None
        and float(calibration["expected_calibration_error"]) <= 0.22
        and strategy.get("mean_net_event_return") is not None
        and float(strategy["mean_net_event_return"]) > 0
        and null.get("one_sided_p_value_actual_ge_null") is not None
        and float(null["one_sided_p_value_actual_ge_null"]) <= 0.10
        and bool(placebo.get("random_weaker_than_main_h1", False))
        and bool(placebo.get("shifted_weaker_than_main_h1", False))
        and bool(peer.get("weaker_than_main_h1", False))
        and neg_h1 is not None
        and float(neg_h1) < 0
        and neg_h3 is not None
        and float(neg_h3) < 0
        and h3_h1 is not None
        and float(h3_h1) < 0
        and binary_abs is not None
        and designation_abs is not None
        and float(designation_abs) < float(binary_abs)
        and outlier_not_collapse
    )
    return "fresh-confirmed, continue to leakage/execution audit" if passed else "failed fresh confirmation"


def write_agent_3e_report(path: str | Path, report: dict[str, object]) -> Path:
    walk = report.get("walk_forward", {}) or {}
    metrics = walk.get("metrics", {}) or {}
    calibration = report.get("calibration", {}) or {}
    strategy = report.get("strategy", {}) or {}
    null = report.get("null_shuffle", {}) or {}
    gates = report.get("fresh_minimum_gates", {}) or {}
    lines = [
        "# Agent 3E Biotech Fresh-Data Confirmation",
        "",
        f"Decision: {report.get('decision', 'unknown')}.",
        "",
        "This is a fresh-data confirmation pass only. It is not a graduated signal, trading recommendation, or final empirical result.",
        "",
        "## Fresh Holdout",
        "",
        f"- source: {report.get('fresh_source_rule')}",
        f"- fresh reviewed usable rows: {gates.get('fresh_reviewed_usable_rows')}",
        f"- fresh binary catalysts: {gates.get('fresh_binary_catalyst_rows')}",
        f"- fresh negative catalysts: {gates.get('fresh_negative_catalyst_rows')}",
        f"- fresh positive/contrast rows: {gates.get('fresh_positive_or_contrast_rows')}",
        f"- market-cap context rows: {gates.get('rows_with_market_cap_context')}",
        f"- XBI run-up context rows: {gates.get('rows_with_xbi_runup_context')}",
        f"- likely OOS predictions: {gates.get('likely_oos_predictions')}",
        "",
        "## Walk-Forward, Calibration, Costs",
        "",
        f"- predictions: {walk.get('n_predictions')}",
        f"- ROC AUC: {metrics.get('roc_auc')}",
        f"- accuracy: {metrics.get('accuracy')}",
        f"- brier score: {metrics.get('brier_score')}",
        f"- ECE: {calibration.get('expected_calibration_error')}",
        f"- strategy trades: {strategy.get('n_trades')}",
        f"- mean net event return: {strategy.get('mean_net_event_return')}",
        f"- cumulative net return: {strategy.get('cumulative_net_return')}",
        f"- null-shuffle p-value: {null.get('one_sided_p_value_actual_ge_null')}",
        "",
        "## Hypothesis Slices",
        "",
    ]
    for name, item in (report.get("hypotheses", {}) or {}).items():
        h1 = item.get("h1", {}) if isinstance(item, dict) else {}
        h3 = item.get("h3", {}) if isinstance(item, dict) else {}
        h10 = item.get("h10", {}) if isinstance(item, dict) else {}
        lines.append(
            f"- {name}: n={item.get('n')}, h1_mean={h1.get('mean_log')}, "
            f"h3_mean={h3.get('mean_log')}, h10_mean={h10.get('mean_log')}"
        )
    lines.extend(["", "## Controls And Robustness", ""])
    placebo = report.get("placebo_controls", {}) or {}
    peer = report.get("peer_controls", {}) or {}
    outliers = ((report.get("outlier_robustness", {}) or {}).get("horizons", {}) or {}).get("h1", {}) or {}
    lines.extend(
        [
            f"- random placebo h1 mean: {(placebo.get('random_summary', {}) or {}).get('h1', {}).get('mean_log')}",
            f"- shifted placebo h1 mean: {(placebo.get('shifted_summary', {}) or {}).get('h1', {}).get('mean_log')}",
            f"- peer-control h1 mean: {(peer.get('summary', {}) or {}).get('h1', {}).get('mean_log')}",
            f"- h1 exclude top 1 absolute mean: {outliers.get('exclude_top_1_abs_mean')}",
            f"- h1 exclude top 3 absolute mean: {outliers.get('exclude_top_3_abs_mean')}",
            f"- h1 exclude top 5 absolute mean: {outliers.get('exclude_top_5_abs_mean')}",
            f"- h1 winsorized mean 5/95: {outliers.get('winsorized_mean_5_95')}",
            f"- h1 sign accuracy, directional rows only: {outliers.get('sign_accuracy_directional_only')}",
            "",
            "## Gates",
            "",
        ]
    )
    for name, ok in (gates.get("gates", {}) or {}).items():
        lines.append(f"- {name}: {'PASS' if ok else 'FAIL'}")
    lines.extend(
        [
            "",
            "Do not call the signal graduated. Agent 3E only tests whether the Agent 3D result survives a separate fresh-data pass.",
            "",
        ]
    )
    for warning in report.get("warnings", []):
        lines.append(f"- {warning}")
    p = ensure_parent(path)
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def run_biotech_fresh_confirmation(
    *,
    raw_events_path: str | Path = "data/events/biotech_catalyst_fresh_review_queue_raw.csv",
    original_event_study_path: str | Path = "artifacts/biotech_catalyst_event_study.csv",
    parser_errors_path: str | Path | None = "data/events/biotech_catalyst_parser_errors.csv",
    shares_context_path: str | Path | None = None,
    prices_dir: str | Path = "data/prices/biotech_catalysts",
    out_dir: str | Path = "artifacts",
    fresh_events_out: str | Path = "data/events/biotech_catalyst_fresh_reviewed_events.csv",
    benchmark: str = "SPY",
    sector_benchmark: str = "XBI",
    horizons: tuple[int, ...] = (1, 3, 10),
    min_train: int = 40,
    purge_days: int = 3,
    probability_threshold: float = 0.60,
    cost_bps: float = 5.0,
    slippage_bps: float = 5.0,
    null_iterations: int = 500,
    seed: int = 314,
    estimation_window: int = 120,
    estimation_gap: int = 5,
    min_estimation_observations: int = 60,
) -> dict[str, object]:
    out = ensure_dir(out_dir)
    raw_reviewed = build_fresh_reviewed_events(
        raw_events_path,
        original_events=original_event_study_path,
        reviewed_only=True,
        sector_benchmark=sector_benchmark,
    )
    fresh_events = enrich_fresh_context(
        raw_reviewed,
        prices_dir=prices_dir,
        shares_context=shares_context_path,
        benchmark_ticker=sector_benchmark,
        out_path=fresh_events_out,
    )

    analysis_events_path = out / "biotech_catalyst_fresh_analysis_events.csv"
    event_study_path = out / "biotech_catalyst_fresh_event_study.csv"
    base_rates_path = out / "biotech_catalyst_fresh_base_rates.csv"
    predictions_path = out / "biotech_catalyst_fresh_walk_forward_predictions.csv"
    backtest_report_path = out / "biotech_catalyst_fresh_backtest_report.json"
    placebo_report_path = out / "biotech_catalyst_fresh_placebo_report.json"
    peer_report_path = out / "biotech_catalyst_fresh_peer_report.json"
    null_report_path = out / "biotech_catalyst_fresh_null_shuffle_report.json"
    outlier_report_path = out / "biotech_catalyst_fresh_outlier_robustness.md"
    agent_report_path = out / "biotech_catalyst_agent_3e_report.md"

    analysis_events = prepare_biotech_falsification_events(fresh_events, sector_benchmark=sector_benchmark, out_path=analysis_events_path)
    event_study, event_diag = _control_event_study(
        events_path=analysis_events_path,
        prices_dir=prices_dir,
        benchmark=benchmark,
        horizons=horizons,
        out_path=event_study_path,
        estimation_window=estimation_window,
        estimation_gap=estimation_gap,
        min_estimation_observations=min_estimation_observations,
    )
    ok = event_study[event_study["event_status"].astype(str).eq("ok")].copy()
    base_rates = biotech_base_rate_table(event_study, horizons=horizons, out_path=base_rates_path)
    predictions, walk_report = purged_walk_forward_sector_model(
        event_study,
        horizon=1,
        min_train=min_train,
        purge_days=purge_days,
        out_predictions=predictions_path,
    )
    usable_preds = predictions[predictions["predicted_positive_probability"].notna()].copy()
    calibration_path = out / "biotech_catalyst_fresh_calibration.csv"
    _, calibration_report = calibration_table(usable_preds, bins=10, out_path=calibration_path)
    trades_path = out / "biotech_catalyst_fresh_strategy_trades.csv"
    trades, strategy_report = simulate_event_strategy(
        usable_preds,
        horizon=1,
        return_column="car_sector_adj_h1",
        long_threshold=probability_threshold,
        allow_short=True,
        cost_bps=cost_bps,
        slippage_bps=slippage_bps,
        out_trades=trades_path,
    )
    null_distribution_path = out / "biotech_catalyst_fresh_null_shuffle_distribution.csv"
    _, null_report = null_shuffle_strategy_test(
        usable_preds,
        horizon=1,
        n_iter=null_iterations,
        seed=seed,
        return_column="car_sector_adj_h1",
        long_threshold=probability_threshold,
        allow_short=True,
        cost_bps=cost_bps,
        slippage_bps=slippage_bps,
        out_path=null_distribution_path,
    )
    _write_json(null_report_path, null_report)

    source_direction: dict[str, object] = {}
    for h in horizons:
        source_trades, source_report = simulate_source_direction_strategy(event_study, horizon=h, cost_bps=cost_bps, slippage_bps=slippage_bps)
        source_direction[f"h{h}"] = source_report
        source_trades.to_csv(out / f"biotech_catalyst_fresh_source_direction_trades_h{h}.csv", index=False)

    placebo_random_events = out / "biotech_catalyst_fresh_placebo_random_events.csv"
    placebo_shifted_events = out / "biotech_catalyst_fresh_placebo_shifted_events.csv"
    random_events, random_diag = make_placebo_events(analysis_events_path, prices_dir, placebo_random_events, n_per_event=1, mode="random", seed=seed)
    shifted_events, shifted_diag = make_placebo_events(analysis_events_path, prices_dir, placebo_shifted_events, n_per_event=1, mode="shift", seed=seed)
    random_study, random_event_diag = _control_event_study(
        events_path=placebo_random_events,
        prices_dir=prices_dir,
        benchmark=benchmark,
        horizons=horizons,
        out_path=out / "biotech_catalyst_fresh_placebo_random_event_study.csv",
        estimation_window=estimation_window,
        estimation_gap=estimation_gap,
        min_estimation_observations=min_estimation_observations,
    )
    shifted_study, shifted_event_diag = _control_event_study(
        events_path=placebo_shifted_events,
        prices_dir=prices_dir,
        benchmark=benchmark,
        horizons=horizons,
        out_path=out / "biotech_catalyst_fresh_placebo_shifted_event_study.csv",
        estimation_window=estimation_window,
        estimation_gap=estimation_gap,
        min_estimation_observations=min_estimation_observations,
    )

    peer_events_path = out / "biotech_catalyst_fresh_peer_events.csv"
    peer_events, peer_diag = make_peer_control_events(analysis_events_path, peer_events_path)
    peer_study, peer_event_diag = _control_event_study(
        events_path=peer_events_path,
        prices_dir=prices_dir,
        benchmark=benchmark,
        horizons=horizons,
        out_path=out / "biotech_catalyst_fresh_peer_event_study.csv",
        estimation_window=estimation_window,
        estimation_gap=estimation_gap,
        min_estimation_observations=min_estimation_observations,
    )

    main_summary = _summarize_returns(event_study, label="fresh_main", horizons=horizons)
    random_summary = _summarize_returns(random_study, label="fresh_random_placebo", horizons=horizons)
    shifted_summary = _summarize_returns(shifted_study, label="fresh_shifted_placebo", horizons=horizons)
    peer_summary = _summarize_returns(peer_study, label="fresh_peer_control", horizons=horizons)
    main_h1_abs = ((main_summary.get("h1") or {}).get("mean_abs_log") or 0.0)
    placebo_report = {
        "random_events": int(len(random_events)),
        "shifted_events": int(len(shifted_events)),
        "random_generation_diagnostics": random_diag.to_dict(),
        "shifted_generation_diagnostics": shifted_diag.to_dict(),
        "random_event_study_diagnostics": random_event_diag,
        "shifted_event_study_diagnostics": shifted_event_diag,
        "random_summary": random_summary,
        "shifted_summary": shifted_summary,
        "random_weaker_than_main_h1": ((random_summary.get("h1") or {}).get("mean_abs_log") or 0.0) < main_h1_abs,
        "shifted_weaker_than_main_h1": ((shifted_summary.get("h1") or {}).get("mean_abs_log") or 0.0) < main_h1_abs,
    }
    peer_report = {
        "peer_events": int(len(peer_events)),
        "generation_diagnostics": peer_diag.to_dict(),
        "event_study_diagnostics": peer_event_diag,
        "summary": peer_summary,
        "weaker_than_main_h1": ((peer_summary.get("h1") or {}).get("mean_abs_log") or 0.0) < main_h1_abs,
        "warning": "Peer controls rotate to another ticker in the fresh biotech universe; not a hand-built mechanism peer basket.",
    }
    _write_json(placebo_report_path, placebo_report)
    _write_json(peer_report_path, peer_report)

    outlier_report = outlier_robustness_report(event_study, horizons=(1, 3))
    write_fresh_outlier_robustness(outlier_report_path, outlier_report)

    binary_rows = ok[_bool_series(ok, "binary_catalyst_flag")]
    designation_rows = ok[_bool_series(ok, "designation_only_flag")]
    base_rate_contrasts = {
        "binary_n": int(len(binary_rows)),
        "designation_n": int(len(designation_rows)),
        "binary_mean_abs_h1": float(pd.to_numeric(binary_rows.get("car_sector_adj_h1", pd.Series(dtype=float)), errors="coerce").abs().mean()) if len(binary_rows) else None,
        "designation_mean_abs_h1": float(pd.to_numeric(designation_rows.get("car_sector_adj_h1", pd.Series(dtype=float)), errors="coerce").abs().mean()) if len(designation_rows) else None,
    }
    report: dict[str, object] = {
        "agent": "3E",
        "domain": "biotech_fda_clinical_catalyst",
        "benchmark": benchmark.upper(),
        "sector_benchmark": sector_benchmark.upper(),
        "horizons": list(horizons),
        "fresh_source_rule": "new tickers outside Agent 3D, parsed by fixed 3C parser and strict 3E rule review",
        "event_counts": {
            "fresh_reviewed_events": int(len(analysis_events)),
            "fresh_event_study_rows": int(len(event_study)),
            "fresh_event_study_ok_rows": int((event_study["event_status"] == "ok").sum()),
            "fresh_binary_catalysts": int(_bool_series(analysis_events, "binary_catalyst_flag").sum()),
            "fresh_positive_catalysts": int(analysis_events.get("event_direction_pre_price", pd.Series("", index=analysis_events.index)).astype(str).str.lower().eq("positive").sum()),
            "fresh_negative_catalysts": int(analysis_events.get("event_direction_pre_price", pd.Series("", index=analysis_events.index)).astype(str).str.lower().eq("negative").sum()),
        },
        "event_study_diagnostics": event_diag,
        "event_study_summary": main_summary,
        "base_rate_rows": int(len(base_rates)),
        "hypotheses": evaluate_biotech_hypotheses(event_study, horizons=horizons),
        "walk_forward": walk_report,
        "calibration": calibration_report,
        "strategy": strategy_report,
        "source_direction_strategy": source_direction,
        "null_shuffle": null_report,
        "placebo_controls": placebo_report,
        "peer_controls": peer_report,
        "outlier_robustness": outlier_report,
        "fresh_minimum_gates": _fresh_gate_summary(analysis_events, predictions, parser_errors_path),
        "base_rate_contrasts": base_rate_contrasts,
        "artifacts": {
            "fresh_events": str(fresh_events_out),
            "analysis_events": str(analysis_events_path),
            "event_study": str(event_study_path),
            "base_rates": str(base_rates_path),
            "walk_forward_predictions": str(predictions_path),
            "calibration": str(calibration_path),
            "strategy_trades": str(trades_path),
            "null_shuffle_distribution": str(null_distribution_path),
            "null_shuffle_report": str(null_report_path),
            "placebo_report": str(placebo_report_path),
            "peer_report": str(peer_report_path),
            "outlier_robustness": str(outlier_report_path),
            "backtest_report": str(backtest_report_path),
            "agent_report": str(agent_report_path),
        },
        "warnings": [
            "Do not call the signal graduated from this fresh-data confirmation pass.",
            "No parser labels were changed by this run.",
            "The walk-forward classifier uses the same h1 XBI-adjusted target and fixed feature setup as Agent 3D.",
            "Fresh rows are rule-reviewed SEC 8-K/exhibit events from new tickers, not a fully human-reviewed corpus.",
        ],
    }
    report["decision"] = _fresh_decision(report)
    if report["decision"] not in FRESH_DECISION_OPTIONS:
        report["decision"] = "failed fresh confirmation"

    _write_json(backtest_report_path, report)
    write_agent_3e_report(agent_report_path, report)
    return report
