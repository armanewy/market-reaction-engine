from __future__ import annotations

import json
from math import exp, sqrt
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .backtest import (
    calibration_table,
    make_peer_control_events,
    make_placebo_events,
    null_shuffle_strategy_test,
    purged_walk_forward_direction_model,
    simulate_event_strategy,
)
from .event_study import run_event_study
from .paths import ensure_dir, ensure_parent


GOVERNMENT_CONTRACT_DECISION_OPTIONS = {
    "promising, require fresh-data confirmation",
    "underpowered",
    "failed falsification",
    "timestamp/public-awareness issue found",
    "mapping/context issue found",
    "domain not promising",
}

LARGE_PRIME_TICKERS = {"LMT", "RTX", "NOC", "GD", "BA", "HII", "LHX"}
DEFAULT_PEER_MAP = {
    "LMT": "NOC",
    "NOC": "LMT",
    "RTX": "LHX",
    "LHX": "RTX",
    "GD": "HII",
    "HII": "GD",
    "BA": "RTX",
    "CACI": "SAIC",
    "SAIC": "CACI",
    "LDOS": "BAH",
    "BAH": "LDOS",
    "PLTR": "CACI",
    "KTOS": "AVAV",
    "AVAV": "KTOS",
    "MRCY": "KTOS",
    "RKLB": "RDW",
    "RDW": "RKLB",
    "BKSY": "PL",
    "LUNR": "RKLB",
    "PL": "BKSY",
}


def _clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null", "nat"}:
        return ""
    return text


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _bool_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    return df[column].map(_bool_value)


def _num_series(df: pd.DataFrame, column: str, default: float = np.nan) -> pd.Series:
    if column not in df.columns:
        return pd.Series(default, index=df.index, dtype=float)
    return pd.to_numeric(df[column], errors="coerce")


def _simple_from_log(value: object) -> float:
    try:
        x = float(value)
    except Exception:
        return float("nan")
    if np.isnan(x):
        return float("nan")
    return float(exp(x) - 1.0)


def _to_jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


def _write_json(path: str | Path, payload: dict[str, object]) -> Path:
    p = ensure_parent(path)
    p.write_text(json.dumps(_to_jsonable(payload), indent=2, default=str), encoding="utf-8")
    return p


def _control_event_study(
    *,
    events_path: Path,
    prices_dir: str | Path,
    benchmark: str,
    horizons: tuple[int, ...],
    out_path: Path,
    estimation_window: int,
    estimation_gap: int,
    min_estimation_observations: int,
) -> tuple[pd.DataFrame, dict[str, object]]:
    study, diag = run_event_study(
        events_path,
        prices_dir,
        benchmark_ticker=benchmark,
        horizons=horizons,
        estimation_window=estimation_window,
        estimation_gap=estimation_gap,
        min_estimation_observations=min_estimation_observations,
    )
    ensure_parent(out_path)
    study.to_csv(out_path, index=False)
    return study, {
        "events_total": diag.events_total,
        "events_ok": diag.events_ok,
        "events_skipped": diag.events_skipped,
        "skipped_reasons": diag.skipped_reasons,
    }


def _choose_sector_benchmark(prices_dir: str | Path, candidates: Iterable[str] = ("ITA", "XAR", "PPA")) -> tuple[str, str]:
    prices = Path(prices_dir)
    for ticker in candidates:
        if (prices / f"{ticker.upper()}.csv").exists():
            return ticker.upper(), ""
    return "SPY", "Defense/aerospace ETF prices were not available locally; SPY is used as the sector-control fallback."


def _materiality_bucket(values: pd.Series) -> pd.Series:
    v = pd.to_numeric(values, errors="coerce")
    return pd.cut(
        v,
        bins=[-np.inf, 0.005, 0.01, 0.02, 0.05, np.inf],
        labels=["lt_0_5pct", "0_5pct_to_1pct", "1pct_to_2pct", "2pct_to_5pct", "gte_5pct"],
    ).astype(str).replace("nan", "unknown")


def prepare_government_contract_falsification_events(
    events: str | Path | pd.DataFrame,
    *,
    prices_dir: str | Path = "data/prices/government_contracts",
    out_path: str | Path | None = None,
) -> tuple[pd.DataFrame, str]:
    """Prepare public-linked government-contract rows for first-pass falsification."""
    df = pd.read_csv(events) if not isinstance(events, pd.DataFrame) else events.copy()
    if df.empty:
        raise ValueError("No government-contract rows supplied")

    source_type = df.get("public_announcement_source_type", df.get("source_type", pd.Series("", index=df.index))).fillna("").astype(str).str.lower()
    link_conf = _num_series(df, "public_announcement_link_confidence", default=0.0)
    mapping_conf = _num_series(df, "recipient_mapping_confidence", default=0.0)
    duplicate = df.get("duplicate_status", pd.Series("", index=df.index)).fillna("").astype(str).str.lower()
    ratio_present = _num_series(df, "obligated_amount_pct_market_cap").notna() | _num_series(df, "award_amount_pct_market_cap").notna()
    has_amount = _num_series(df, "obligated_amount").notna() | _num_series(df, "award_amount").notna()
    review = df.get("review_status", pd.Series("", index=df.index)).fillna("").astype(str).str.lower()
    session = df.get("release_session", pd.Series("", index=df.index)).fillna("").astype(str).str.lower()
    event_time = pd.to_datetime(
        df.get("event_time", pd.Series(pd.NaT, index=df.index)),
        errors="coerce",
        utc=True,
    )

    mask = (
        review.isin({"approved", "reviewed", "curated"})
        & _bool_series(df, "model_eligible_public_announcement_flag")
        & link_conf.ge(0.80)
        & source_type.ne("usaspending_only")
        & mapping_conf.ge(0.80)
        & _bool_series(df, "actual_funded_award_flag")
        & has_amount
        & ratio_present
        & duplicate.eq("primary")
        & event_time.notna()
        & session.ne("unknown")
    )
    out = df[mask].copy()
    if out.empty:
        raise ValueError("No model-eligible public-linked government-contract rows found")
    out["event_time"] = event_time.loc[out.index].dt.tz_convert(None).dt.strftime("%Y-%m-%dT%H:%M:%S")

    sector_benchmark, limitation = _choose_sector_benchmark(prices_dir)
    gov_type = out.get("government_contract_event_type", out.get("event_subtype", pd.Series("government_contract", index=out.index))).fillna("government_contract").astype(str).str.lower()
    out["event_type"] = gov_type
    out["event_subtype"] = gov_type
    out["event_family"] = "government_contract_awards"
    out["sector_benchmark"] = sector_benchmark
    out["expectedness"] = "unknown"
    out["surprise_direction"] = "positive_award"
    out["surprise_magnitude"] = "unknown"
    out["summary"] = out.get("summary", pd.Series("", index=out.index)).fillna("").astype(str)
    out["summary"] = out["summary"].where(out["summary"].str.strip().ne(""), out["ticker"].astype(str) + " public government contract award")

    bucket = out.get("company_size_bucket", pd.Series("unknown", index=out.index)).fillna("unknown").astype(str).str.lower()
    small_mid = bucket.isin({"micro_cap", "small_cap", "mid_cap", "small_300m_2b", "mid_2b_10b"}) | _bool_series(out, "small_cap_flag")
    out["small_mid_cap_flag"] = small_mid
    out["large_prime_flag"] = out["ticker"].fillna("").astype(str).str.upper().isin(LARGE_PRIME_TICKERS)
    obligated_pct = _num_series(out, "obligated_amount_pct_market_cap")
    award_pct = _num_series(out, "award_amount_pct_market_cap")
    best_pct = pd.concat([obligated_pct, award_pct], axis=1).max(axis=1)
    out["large_prime_low_materiality_flag"] = out["large_prime_flag"] & best_pct.lt(0.01)
    out["obligated_materiality_bucket"] = _materiality_bucket(obligated_pct)
    out["award_materiality_bucket"] = _materiality_bucket(award_pct)
    out["pre_event_runup_positive_flag"] = _num_series(out, "pre_event_market_adjusted_return_20d").gt(0)
    out["material_award_1pct_flag"] = best_pct.ge(0.01)
    out["material_award_5pct_flag"] = best_pct.ge(0.05)
    out["materiality"] = best_pct.mul(10.0).clip(0.0, 1.0).fillna(0.0)

    if out_path:
        p = ensure_parent(out_path)
        out.to_csv(p, index=False)
    return out.reset_index(drop=True), limitation


def _summary_for_group(frame: pd.DataFrame, *, label: str, horizons: Iterable[int]) -> dict[str, object]:
    out: dict[str, object] = {"label": label, "rows": int(len(frame))}
    ok = frame[frame.get("event_status", "ok").astype(str).eq("ok")].copy() if "event_status" in frame.columns else frame.copy()
    out["ok_rows"] = int(len(ok))
    for h in horizons:
        col = f"car_market_model_h{h}"
        s = pd.to_numeric(ok.get(col, pd.Series(dtype=float)), errors="coerce").dropna()
        out[f"h{h}"] = {
            "n": int(len(s)),
            "mean_log": float(s.mean()) if len(s) else None,
            "median_log": float(s.median()) if len(s) else None,
            "mean_simple": float(s.map(_simple_from_log).mean()) if len(s) else None,
            "positive_rate": float((s > 0).mean()) if len(s) else None,
            "mean_abs_log": float(s.abs().mean()) if len(s) else None,
        }
    return out


def _append_group_summary(rows: list[dict[str, object]], frame: pd.DataFrame, *, group_name: str, group_value: str, horizons: Iterable[int]) -> None:
    for h in horizons:
        col = f"car_market_model_h{h}"
        s = pd.to_numeric(frame.get(col, pd.Series(dtype=float)), errors="coerce").dropna()
        if s.empty:
            continue
        simple = s.map(_simple_from_log)
        rows.append(
            {
                "group_name": group_name,
                "group_value": group_value,
                "horizon": h,
                "n": int(len(s)),
                "positive_rate": float((s > 0).mean()),
                "negative_rate": float((s < 0).mean()),
                "mean_car_market_model": float(s.mean()),
                "median_car_market_model": float(s.median()),
                "std_car_market_model": float(s.std(ddof=1)) if len(s) > 1 else np.nan,
                "stderr_car_market_model": float(s.std(ddof=1) / sqrt(len(s))) if len(s) > 1 else np.nan,
                "mean_simple_market_model": float(simple.mean()),
                "median_simple_market_model": float(simple.median()),
                "mean_abs_car_market_model": float(s.abs().mean()),
            }
        )


def government_contract_base_rate_table(
    event_study: str | Path | pd.DataFrame,
    *,
    horizons: Iterable[int] = (1, 3, 10),
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    df = pd.read_csv(event_study) if not isinstance(event_study, pd.DataFrame) else event_study.copy()
    frame = df[df.get("event_status", "ok").astype(str).eq("ok")].copy() if "event_status" in df.columns else df.copy()
    rows: list[dict[str, object]] = []
    _append_group_summary(rows, frame, group_name="all", group_value="all", horizons=horizons)
    group_cols = [
        "small_mid_cap_flag",
        "large_prime_flag",
        "large_prime_low_materiality_flag",
        "obligated_materiality_bucket",
        "award_materiality_bucket",
        "agency",
        "actual_funded_award_flag",
        "ceiling_only_flag",
        "new_work_flag",
        "modification_flag",
        "option_exercise_flag",
        "government_contract_event_type",
        "company_size_bucket",
    ]
    for col in group_cols:
        if col not in frame.columns:
            continue
        keys = frame[col].fillna("unknown").astype(str).str.lower().str.strip()
        for value, group in frame.groupby(keys, dropna=False):
            _append_group_summary(rows, group, group_name=col, group_value=str(value), horizons=horizons)
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["horizon", "group_name", "n", "mean_car_market_model"], ascending=[True, True, False, False]).reset_index(drop=True)
    if out_path:
        p = ensure_parent(out_path)
        out.to_csv(p, index=False)
    return out


def _hypothesis_masks(df: pd.DataFrame) -> dict[str, tuple[pd.Series, str, str]]:
    obligated_pct = _num_series(df, "obligated_amount_pct_market_cap")
    award_pct = _num_series(df, "award_amount_pct_market_cap")
    best_pct = pd.concat([obligated_pct, award_pct], axis=1).max(axis=1)
    runup = _num_series(df, "pre_event_market_adjusted_return_20d")
    small_mid = _bool_series(df, "small_mid_cap_flag")
    large_prime = _bool_series(df, "large_prime_flag")
    funded = _bool_series(df, "actual_funded_award_flag")
    material = funded & best_pct.ge(0.01)
    return {
        "h1_material_small_mid_award": (
            small_mid & funded & obligated_pct.ge(0.01),
            "positive",
            "small/mid-cap, actual funded award, obligated_amount_pct_market_cap >= 1%",
        ),
        "h2_highly_material_small_mid_award": (
            small_mid & funded & obligated_pct.ge(0.05),
            "strong_positive",
            "small/mid-cap, actual funded award, obligated_amount_pct_market_cap >= 5%",
        ),
        "h3_large_prime_low_materiality_control": (
            large_prime & obligated_pct.lt(0.01),
            "weak_or_none",
            "large-prime ticker and obligated_amount_pct_market_cap < 1%",
        ),
        "h4_ceiling_only_contrast": (
            _bool_series(df, "ceiling_only_flag"),
            "weaker_noisier",
            "ceiling_only_flag=true",
        ),
        "h5_positive_runup_material_award": (
            runup.gt(0) & material,
            "weaker_or_sell_the_news",
            "pre_event_market_adjusted_return_20d > 0 and material award >= 1% market cap",
        ),
    }


def evaluate_government_contract_hypotheses(event_study: pd.DataFrame, *, horizons: Iterable[int] = (1, 3, 10)) -> dict[str, object]:
    ok = event_study[event_study.get("event_status", "ok").astype(str).eq("ok")].copy() if "event_status" in event_study.columns else event_study.copy()
    out: dict[str, object] = {}
    for name, (mask, expected, definition) in _hypothesis_masks(ok).items():
        subset = ok[mask.fillna(False)].copy()
        item: dict[str, object] = {"definition": definition, "expected": expected, "n": int(len(subset))}
        for h in horizons:
            s = pd.to_numeric(subset.get(f"car_market_model_h{h}", pd.Series(dtype=float)), errors="coerce").dropna()
            if s.empty:
                item[f"h{h}"] = {"n": 0}
                continue
            aligned = s > 0 if expected in {"positive", "strong_positive"} else pd.Series([np.nan] * len(s))
            item[f"h{h}"] = {
                "n": int(len(s)),
                "mean_log": float(s.mean()),
                "median_log": float(s.median()),
                "mean_simple": float(s.map(_simple_from_log).mean()),
                "positive_rate": float((s > 0).mean()),
                "negative_rate": float((s < 0).mean()),
                "alignment_rate": float(aligned.mean()) if expected in {"positive", "strong_positive"} else None,
                "mean_abs_log": float(s.abs().mean()),
            }
        out[name] = item
    return out


def _materiality_sensitivity(event_study: pd.DataFrame, *, horizons: Iterable[int] = (1, 3, 10)) -> list[dict[str, object]]:
    ok = event_study[event_study.get("event_status", "ok").astype(str).eq("ok")].copy()
    best_pct = pd.concat([
        _num_series(ok, "obligated_amount_pct_market_cap"),
        _num_series(ok, "award_amount_pct_market_cap"),
    ], axis=1).max(axis=1)
    rows: list[dict[str, object]] = []
    for threshold in [0.005, 0.01, 0.02, 0.05]:
        for label, mask in {
            "all": best_pct.ge(threshold),
            "small_mid": best_pct.ge(threshold) & _bool_series(ok, "small_mid_cap_flag"),
            "large_prime": best_pct.ge(threshold) & _bool_series(ok, "large_prime_flag"),
        }.items():
            subset = ok[mask.fillna(False)].copy()
            for h in horizons:
                s = pd.to_numeric(subset.get(f"car_market_model_h{h}", pd.Series(dtype=float)), errors="coerce").dropna()
                rows.append(
                    {
                        "threshold": threshold,
                        "slice": label,
                        "horizon": h,
                        "n": int(len(s)),
                        "mean_log": float(s.mean()) if len(s) else np.nan,
                        "mean_simple": float(s.map(_simple_from_log).mean()) if len(s) else np.nan,
                        "positive_rate": float((s > 0).mean()) if len(s) else np.nan,
                    }
                )
    return rows


def write_government_contract_materiality_sensitivity(path: str | Path, sensitivity: list[dict[str, object]]) -> Path:
    lines = [
        "# Government Contract Materiality Sensitivity",
        "",
        "This sensitivity table is part of Agent 4G's first falsification pass. It is not a signal graduation.",
        "",
        "| threshold | slice | horizon | n | mean simple abnormal return | positive rate |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for row in sensitivity:
        mean_simple = row.get("mean_simple")
        positive = row.get("positive_rate")
        lines.append(
            f"| {float(row['threshold']):.3f} | {row['slice']} | {row['horizon']} | {row['n']} | "
            f"{'' if pd.isna(mean_simple) else f'{float(mean_simple):.6f}'} | {'' if pd.isna(positive) else f'{float(positive):.3f}'} |"
        )
    p = ensure_parent(path)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _write_peer_map(path: str | Path, tickers: Iterable[str]) -> Path:
    rows = []
    available = {str(t).upper() for t in tickers}
    for ticker in sorted(available):
        peer = DEFAULT_PEER_MAP.get(ticker)
        if peer and peer in available:
            rows.append({"ticker": ticker, "peer_ticker": peer})
    p = ensure_parent(path)
    pd.DataFrame(rows).to_csv(p, index=False)
    return p


def _decision(report: dict[str, object]) -> str:
    walk = report.get("walk_forward", {}) or {}
    metrics = walk.get("metrics", {}) if isinstance(walk, dict) else {}
    calibration = report.get("calibration", {}) or {}
    strategy = report.get("strategy", {}) or {}
    null = report.get("null_shuffle", {}) or {}
    hypotheses = report.get("hypotheses", {}) or {}
    placebo = report.get("placebo_controls", {}) or {}
    peer = report.get("peer_controls", {}) or {}

    if int(walk.get("n_predictions", 0) or 0) < 30:
        return "underpowered"
    if report.get("timestamp_issue_found"):
        return "timestamp/public-awareness issue found"
    if report.get("mapping_context_issue_found"):
        return "mapping/context issue found"

    h1 = hypotheses.get("h1_material_small_mid_award", {}) if isinstance(hypotheses, dict) else {}
    h3 = hypotheses.get("h3_large_prime_low_materiality_control", {}) if isinstance(hypotheses, dict) else {}
    h1_mean = (h1.get("h1", {}) or {}).get("mean_log") if isinstance(h1, dict) else None
    h3_mean = (h3.get("h1", {}) or {}).get("mean_log") if isinstance(h3, dict) else None
    roc_auc = metrics.get("roc_auc") if isinstance(metrics, dict) else None
    ece = calibration.get("expected_calibration_error") if isinstance(calibration, dict) else None
    mean_net = strategy.get("mean_net_event_return") if isinstance(strategy, dict) else None
    null_p = null.get("one_sided_p_value_actual_ge_null") if isinstance(null, dict) else None
    main_abs = ((report.get("event_study_summary", {}) or {}).get("h1", {}) or {}).get("mean_abs_log") or 0.0
    placebo_abs = max(
        ((placebo.get("random_summary", {}) or {}).get("h1", {}) or {}).get("mean_abs_log") or 0.0,
        ((placebo.get("shifted_summary", {}) or {}).get("h1", {}) or {}).get("mean_abs_log") or 0.0,
    )
    peer_abs = ((peer.get("summary", {}) or {}).get("h1", {}) or {}).get("mean_abs_log") or 0.0

    promising = (
        roc_auc is not None
        and float(roc_auc) > 0.58
        and ece is not None
        and float(ece) <= 0.22
        and mean_net is not None
        and float(mean_net) > 0
        and null_p is not None
        and float(null_p) <= 0.10
        and h1_mean is not None
        and float(h1_mean) > 0
        and h3_mean is not None
        and float(h1_mean) > float(h3_mean)
        and placebo_abs < main_abs
        and peer_abs < main_abs
    )
    return "promising, require fresh-data confirmation" if promising else "failed falsification"


def write_government_contract_agent_4g_report(path: str | Path, report: dict[str, object]) -> Path:
    walk = report.get("walk_forward", {}) or {}
    metrics = walk.get("metrics", {}) or {}
    calibration = report.get("calibration", {}) or {}
    strategy = report.get("strategy", {}) or {}
    null = report.get("null_shuffle", {}) or {}
    lines = [
        "# Agent 4G Government Contract First Falsification Pass",
        "",
        f"Decision: {report.get('decision', 'unknown')}.",
        "",
        "This is a first falsification pass only. Do not call the signal graduated.",
        "",
        "## Inputs",
        "",
        f"- public-linked analysis events: {report.get('event_counts', {}).get('analysis_events')}",
        f"- event-study ok rows: {report.get('event_study_diagnostics', {}).get('events_ok')}",
        f"- small/mid-cap analysis rows: {report.get('event_counts', {}).get('small_mid_cap_rows')}",
        f"- benchmark: {report.get('benchmark')}",
        f"- sector benchmark: {report.get('sector_benchmark')}",
        f"- sector-control limitation: {report.get('sector_control_limitation') or 'none'}",
        "",
        "## Walk-Forward And Costs",
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
        "## Hypotheses",
        "",
    ]
    for name, item in (report.get("hypotheses", {}) or {}).items():
        h1 = item.get("h1", {}) if isinstance(item, dict) else {}
        h3 = item.get("h3", {}) if isinstance(item, dict) else {}
        h10 = item.get("h10", {}) if isinstance(item, dict) else {}
        lines.append(
            f"- {name}: n={item.get('n')}, h1_mean={h1.get('mean_log')}, h1_positive_rate={h1.get('positive_rate')}, "
            f"h3_mean={h3.get('mean_log')}, h10_mean={h10.get('mean_log')}"
        )
    placebo = report.get("placebo_controls", {}) or {}
    peer = report.get("peer_controls", {}) or {}
    lines.extend(
        [
            "",
            "## Controls",
            "",
            f"- random placebo h1 mean: {(placebo.get('random_summary', {}) or {}).get('h1', {}).get('mean_log')}",
            f"- shifted placebo h1 mean: {(placebo.get('shifted_summary', {}) or {}).get('h1', {}).get('mean_log')}",
            f"- peer-control h1 mean: {(peer.get('summary', {}) or {}).get('h1', {}).get('mean_log')}",
            "",
            "## Required Cautions",
            "",
        ]
    )
    for warning in report.get("warnings", []):
        lines.append(f"- {warning}")
    p = ensure_parent(path)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def run_government_contract_falsification_pass(
    *,
    events_path: str | Path = "data/events/government_contract_public_eligible_corpus.csv",
    prices_dir: str | Path = "data/prices/government_contracts",
    out_dir: str | Path = "artifacts",
    benchmark: str = "SPY",
    horizons: tuple[int, ...] = (1, 3, 10),
    min_train: int = 40,
    purge_days: int = 10,
    probability_threshold: float = 0.60,
    cost_bps: float = 5.0,
    slippage_bps: float = 5.0,
    null_iterations: int = 500,
    seed: int = 42,
    estimation_window: int = 120,
    estimation_gap: int = 5,
    min_estimation_observations: int = 60,
) -> dict[str, object]:
    out = ensure_dir(out_dir)
    analysis_events_path = out / "government_contract_analysis_events.csv"
    event_study_path = out / "government_contract_event_study.csv"
    base_rates_path = out / "government_contract_base_rates.csv"
    predictions_path = out / "government_contract_walk_forward_predictions.csv"
    backtest_report_path = out / "government_contract_backtest_report.json"
    placebo_report_path = out / "government_contract_placebo_report.json"
    peer_report_path = out / "government_contract_peer_report.json"
    null_report_path = out / "government_contract_null_shuffle_report.json"
    materiality_path = out / "government_contract_materiality_sensitivity.md"
    agent_report_path = out / "government_contract_agent_4g_report.md"

    analysis_events, sector_limitation = prepare_government_contract_falsification_events(
        events_path,
        prices_dir=prices_dir,
        out_path=analysis_events_path,
    )
    sector_benchmark = _clean_text(analysis_events["sector_benchmark"].iloc[0])
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
    base_rates = government_contract_base_rate_table(event_study, horizons=horizons, out_path=base_rates_path)
    predictions, walk_report = purged_walk_forward_direction_model(
        event_study_path,
        horizon=1,
        min_train=min_train,
        purge_days=purge_days,
        out_predictions=predictions_path,
    )
    usable_preds = predictions[predictions["predicted_positive_probability"].notna()].copy()
    calibration_path = out / "government_contract_calibration.csv"
    _, calibration_report = calibration_table(usable_preds, bins=10, out_path=calibration_path)
    trades_path = out / "government_contract_strategy_trades.csv"
    _, strategy_report = simulate_event_strategy(
        usable_preds,
        horizon=1,
        return_column="car_market_model_h1",
        long_threshold=probability_threshold,
        allow_short=False,
        cost_bps=cost_bps,
        slippage_bps=slippage_bps,
        out_trades=trades_path,
    )
    null_distribution_path = out / "government_contract_null_shuffle_distribution.csv"
    _, null_report = null_shuffle_strategy_test(
        usable_preds,
        horizon=1,
        n_iter=null_iterations,
        seed=seed,
        return_column="car_market_model_h1",
        long_threshold=probability_threshold,
        allow_short=False,
        cost_bps=cost_bps,
        slippage_bps=slippage_bps,
        out_path=null_distribution_path,
    )

    placebo_random_events = out / "government_contract_placebo_random_events.csv"
    placebo_shifted_events = out / "government_contract_placebo_shifted_events.csv"
    random_events, random_diag = make_placebo_events(analysis_events_path, prices_dir, placebo_random_events, n_per_event=1, mode="random", seed=seed)
    shifted_events, shifted_diag = make_placebo_events(analysis_events_path, prices_dir, placebo_shifted_events, n_per_event=1, mode="shift", seed=seed)
    random_study, random_event_diag = _control_event_study(
        events_path=placebo_random_events,
        prices_dir=prices_dir,
        benchmark=benchmark,
        horizons=horizons,
        out_path=out / "government_contract_placebo_random_event_study.csv",
        estimation_window=estimation_window,
        estimation_gap=estimation_gap,
        min_estimation_observations=min_estimation_observations,
    )
    shifted_study, shifted_event_diag = _control_event_study(
        events_path=placebo_shifted_events,
        prices_dir=prices_dir,
        benchmark=benchmark,
        horizons=horizons,
        out_path=out / "government_contract_placebo_shifted_event_study.csv",
        estimation_window=estimation_window,
        estimation_gap=estimation_gap,
        min_estimation_observations=min_estimation_observations,
    )
    peer_map_path = out / "government_contract_peer_map.csv"
    _write_peer_map(peer_map_path, analysis_events["ticker"].dropna().astype(str).str.upper().unique())
    peer_events_path = out / "government_contract_peer_events.csv"
    peer_events, peer_diag = make_peer_control_events(analysis_events_path, peer_events_path, peer_map=peer_map_path)
    peer_study, peer_event_diag = _control_event_study(
        events_path=peer_events_path,
        prices_dir=prices_dir,
        benchmark=benchmark,
        horizons=horizons,
        out_path=out / "government_contract_peer_event_study.csv",
        estimation_window=estimation_window,
        estimation_gap=estimation_gap,
        min_estimation_observations=min_estimation_observations,
    )

    main_summary = _summary_for_group(event_study, label="main", horizons=horizons)
    random_summary = _summary_for_group(random_study, label="random_placebo", horizons=horizons)
    shifted_summary = _summary_for_group(shifted_study, label="shifted_placebo", horizons=horizons)
    peer_summary = _summary_for_group(peer_study, label="peer_control", horizons=horizons)
    placebo_report = {
        "random_events": int(len(random_events)),
        "shifted_events": int(len(shifted_events)),
        "random_generation_diagnostics": random_diag.to_dict(),
        "shifted_generation_diagnostics": shifted_diag.to_dict(),
        "random_event_study_diagnostics": random_event_diag,
        "shifted_event_study_diagnostics": shifted_event_diag,
        "random_summary": random_summary,
        "shifted_summary": shifted_summary,
    }
    peer_report = {
        "peer_events": int(len(peer_events)),
        "peer_map": str(peer_map_path),
        "generation_diagnostics": peer_diag.to_dict(),
        "event_study_diagnostics": peer_event_diag,
        "summary": peer_summary,
        "warning": "Peer controls use a fixed defense/space peer map; they are approximate and should be audited before any signal claim.",
    }
    _write_json(placebo_report_path, placebo_report)
    _write_json(peer_report_path, peer_report)
    _write_json(null_report_path, null_report)

    sensitivity = _materiality_sensitivity(event_study, horizons=horizons)
    write_government_contract_materiality_sensitivity(materiality_path, sensitivity)
    report: dict[str, object] = {
        "agent": "4G",
        "domain": "government_contract_awards",
        "benchmark": benchmark.upper(),
        "sector_benchmark": sector_benchmark,
        "sector_control_limitation": sector_limitation,
        "horizons": list(horizons),
        "event_counts": {
            "analysis_events": int(len(analysis_events)),
            "event_study_rows": int(len(event_study)),
            "event_study_ok_rows": int((event_study["event_status"] == "ok").sum()),
            "small_mid_cap_rows": int(_bool_series(analysis_events, "small_mid_cap_flag").sum()),
            "large_prime_rows": int(_bool_series(analysis_events, "large_prime_flag").sum()),
            "material_1pct_rows": int(_bool_series(analysis_events, "material_award_1pct_flag").sum()),
            "material_5pct_rows": int(_bool_series(analysis_events, "material_award_5pct_flag").sum()),
        },
        "event_study_diagnostics": event_diag,
        "event_study_summary": main_summary,
        "base_rate_rows": int(len(base_rates)),
        "hypotheses": evaluate_government_contract_hypotheses(event_study, horizons=horizons),
        "walk_forward": walk_report,
        "calibration": calibration_report,
        "strategy": strategy_report,
        "null_shuffle": null_report,
        "placebo_controls": placebo_report,
        "peer_controls": peer_report,
        "materiality_sensitivity": sensitivity,
        "timestamp_issue_found": False,
        "mapping_context_issue_found": False,
        "artifacts": {
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
            "materiality_sensitivity": str(materiality_path),
            "backtest_report": str(backtest_report_path),
            "agent_report": str(agent_report_path),
        },
        "warnings": [
            "Do not call the government-contract signal graduated from Agent 4G.",
            "USAspending remains economic verification only; public announcement timestamps drive event_time.",
            "GlobalSecurity mirrors were used only for machine-readable text during manifest buildout, not as timestamp authority.",
            "War.gov/DoD after-close announcements are measured from the next trading day by release_session handling.",
            "Sector-control ETF prices were unavailable unless noted; SPY fallback weakens sector-control interpretation.",
        ],
    }
    report["decision"] = _decision(report)
    if report["decision"] not in GOVERNMENT_CONTRACT_DECISION_OPTIONS:
        report["decision"] = "failed falsification"
    _write_json(backtest_report_path, report)
    write_government_contract_agent_4g_report(agent_report_path, report)
    return report
