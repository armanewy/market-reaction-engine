from __future__ import annotations

import json
from math import exp
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .backtest import make_peer_control_events, make_placebo_events
from .biotech_audit import build_execution_stress_report, build_timestamp_audit
from .biotech_falsification import _control_event_study, _simple_from_log, _summarize_returns
from .paths import ensure_dir, ensure_parent


NEGATIVE_CATALYST_DECISIONS = {
    "negative-catalyst slice fresh-confirmed, continue to final audit",
    "promising but underpowered",
    "failed confirmation",
    "execution unrealistic",
    "outlier-driven",
    "timestamp issue found",
}

PRIMARY_NEGATIVE_EVENT_TYPES = {
    "fda_complete_response_letter",
    "trial_halt",
    "endpoint_failure",
    "safety_signal",
    "trial_discontinuation",
}

NEGATIVE_READOUT_EVENT_TYPES = {
    "phase_2_readout",
    "phase_3_readout",
    "pivotal_trial_readout",
}


def _read_csv(value: str | Path | pd.DataFrame | None) -> pd.DataFrame:
    if value is None:
        return pd.DataFrame()
    if isinstance(value, pd.DataFrame):
        return value.copy()
    p = Path(value)
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null", "nat"}:
        return ""
    return text


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except Exception:
        pass
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _bool_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    return df[column].map(_bool_value)


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
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


def _write_json(path: str | Path, payload: dict[str, object]) -> Path:
    p = ensure_parent(path)
    p.write_text(json.dumps(_to_jsonable(payload), indent=2), encoding="utf-8")
    return p


def _winsorized_mean(series: pd.Series, lower: float = 0.05, upper: float = 0.95) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    lo = values.quantile(lower)
    hi = values.quantile(upper)
    return float(values.clip(lo, hi).mean())


def _negative_catalyst_family(row: pd.Series) -> str:
    event_type = _clean_text(row.get("biotech_catalyst_event_type", row.get("event_type", ""))).lower()
    if event_type == "fda_complete_response_letter":
        return "complete_response_letter"
    if event_type in {"trial_halt", "trial_discontinuation"}:
        return "trial_halt_or_discontinuation"
    if event_type == "safety_signal" or _bool_value(row.get("safety_negative_flag")):
        return "major_safety_signal"
    if event_type == "endpoint_failure" or _bool_value(row.get("trial_failure_flag")):
        return "endpoint_failure_or_trial_failure"
    if event_type in NEGATIVE_READOUT_EVENT_TYPES:
        return "negative_phase_or_pivotal_readout"
    return "other_negative_binary"


def negative_binary_catalyst_mask(df: pd.DataFrame) -> pd.Series:
    """Return the frozen-label Agent 3G primary slice mask."""
    event_type = df.get("biotech_catalyst_event_type", df.get("event_type", pd.Series("", index=df.index))).fillna("").astype(str).str.lower().str.strip()
    direction = df.get("event_direction_pre_price", df.get("surprise_direction", pd.Series("", index=df.index))).fillna("").astype(str).str.lower().str.strip()
    endpoint_met = _bool_series(df, "endpoint_met")
    trial_failure = _bool_series(df, "trial_failure_flag")
    safety_negative = _bool_series(df, "safety_negative_flag")
    designation_only = _bool_series(df, "designation_only_flag")
    binary = _bool_series(df, "binary_catalyst_flag")

    direct_negative = event_type.isin(PRIMARY_NEGATIVE_EVENT_TYPES)
    negative_readout = event_type.isin(NEGATIVE_READOUT_EVENT_TYPES) & (~endpoint_met | trial_failure | safety_negative)
    return binary & direction.eq("negative") & ~designation_only & (direct_negative | negative_readout | trial_failure | safety_negative)


def build_negative_catalyst_event_study(
    original_event_study: str | Path | pd.DataFrame,
    fresh_event_study: str | Path | pd.DataFrame,
    *,
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for split, source in (("original", original_event_study), ("fresh", fresh_event_study)):
        df = _read_csv(source)
        if df.empty:
            continue
        df = df.copy()
        df["dataset_split"] = split
        ok = df.get("event_status", pd.Series("ok", index=df.index)).fillna("ok").astype(str).str.lower().eq("ok")
        frames.append(df[ok & negative_binary_catalyst_mask(df)].copy())
    if not frames:
        out = pd.DataFrame()
    else:
        out = pd.concat(frames, ignore_index=True)
        out["negative_catalyst_family"] = out.apply(_negative_catalyst_family, axis=1)
        out = out.drop_duplicates(["dataset_split", "event_id"]).sort_values(["event_time", "ticker", "event_id"]).reset_index(drop=True)
    if out_path:
        p = ensure_parent(out_path)
        out.to_csv(p, index=False)
    return out


def _append_rate_rows(rows: list[dict[str, object]], frame: pd.DataFrame, *, split: str, group_name: str, group_value: str, horizons: Iterable[int]) -> None:
    for h in horizons:
        col = f"car_sector_adj_h{h}"
        s = pd.to_numeric(frame.get(col, pd.Series(dtype=float)), errors="coerce").dropna()
        if s.empty:
            continue
        simple = s.map(_simple_from_log)
        rows.append(
            {
                "dataset_split": split,
                "group_name": group_name,
                "group_value": group_value,
                "horizon": int(h),
                "n": int(len(s)),
                "expected_direction": "negative",
                "mean_car_sector_adj": float(s.mean()),
                "median_car_sector_adj": float(s.median()),
                "winsorized_mean_car_sector_adj_5_95": _winsorized_mean(s),
                "negative_rate": float((s < 0).mean()),
                "positive_rate": float((s > 0).mean()),
                "sign_accuracy": float((s < 0).mean()),
                "mean_simple_sector_adj": float(simple.mean()),
                "median_simple_sector_adj": float(simple.median()),
                "mean_abs_car_sector_adj": float(s.abs().mean()),
            }
        )


def negative_catalyst_base_rates(
    event_study: str | Path | pd.DataFrame,
    *,
    horizons: Iterable[int] = (1, 3, 10),
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    df = _read_csv(event_study)
    rows: list[dict[str, object]] = []
    splits = [("combined", df)]
    if "dataset_split" in df.columns:
        splits.extend((str(split), group.copy()) for split, group in df.groupby(df["dataset_split"].fillna("unknown").astype(str), dropna=False))
    for split, frame in splits:
        _append_rate_rows(rows, frame, split=split, group_name="all", group_value="all", horizons=horizons)
        for col in ("biotech_catalyst_event_type", "negative_catalyst_family", "market_cap_bucket", "trial_phase"):
            if col not in frame.columns:
                continue
            keys = frame[col].fillna("unknown").astype(str).str.lower().str.strip()
            for value, group in frame.groupby(keys, dropna=False):
                _append_rate_rows(rows, group, split=split, group_name=col, group_value=str(value), horizons=horizons)
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["horizon", "dataset_split", "group_name", "n"], ascending=[True, True, True, False]).reset_index(drop=True)
    if out_path:
        p = ensure_parent(out_path)
        out.to_csv(p, index=False)
    return out


def _loo_summary(values: pd.Series) -> dict[str, object]:
    s = pd.to_numeric(values, errors="coerce").dropna().reset_index(drop=True)
    if len(s) <= 1:
        return {"leave_one_out_min_mean": None, "leave_one_out_max_mean": None}
    means = [float(s.drop(i).mean()) for i in range(len(s))]
    return {"leave_one_out_min_mean": min(means), "leave_one_out_max_mean": max(means)}


def negative_catalyst_outlier_report(event_study: str | Path | pd.DataFrame, *, horizons: Iterable[int] = (1, 3, 10)) -> dict[str, object]:
    df = _read_csv(event_study)
    report: dict[str, object] = {"rows": int(len(df)), "splits": {}}
    split_frames = [("combined", df)]
    if "dataset_split" in df.columns:
        split_frames.extend((str(split), group.copy()) for split, group in df.groupby(df["dataset_split"].fillna("unknown").astype(str), dropna=False))
    for split, frame in split_frames:
        split_report: dict[str, object] = {"rows": int(len(frame)), "horizons": {}}
        for h in horizons:
            col = f"car_sector_adj_h{h}"
            clean = frame[pd.to_numeric(frame.get(col, pd.Series(np.nan, index=frame.index)), errors="coerce").notna()].copy()
            clean["_car"] = pd.to_numeric(clean[col], errors="coerce")
            clean["_abs_car"] = clean["_car"].abs()
            clean = clean.sort_values("_abs_car", ascending=False).reset_index(drop=True)
            s = clean["_car"]
            total_abs = float(clean["_abs_car"].sum()) if len(clean) else 0.0
            item: dict[str, object] = {
                "n": int(len(clean)),
                "mean": float(s.mean()) if len(s) else None,
                "median": float(s.median()) if len(s) else None,
                "winsorized_mean_5_95": _winsorized_mean(s),
                "sign_accuracy": float((s < 0).mean()) if len(s) else None,
                "mean_excluding_top_1_abs": float(clean.iloc[1:]["_car"].mean()) if len(clean) > 1 else None,
                "median_excluding_top_1_abs": float(clean.iloc[1:]["_car"].median()) if len(clean) > 1 else None,
                "mean_excluding_top_3_abs": float(clean.iloc[3:]["_car"].mean()) if len(clean) > 3 else None,
                "median_excluding_top_3_abs": float(clean.iloc[3:]["_car"].median()) if len(clean) > 3 else None,
                "top_1_abs_share": float(clean.head(1)["_abs_car"].sum() / total_abs) if total_abs else None,
                "top_3_abs_share": float(clean.head(3)["_abs_car"].sum() / total_abs) if total_abs else None,
                "largest_abs_events": [
                    {
                        "event_id": _clean_text(row.get("event_id")),
                        "ticker": _clean_text(row.get("ticker")),
                        "event_type": _clean_text(row.get("biotech_catalyst_event_type", row.get("event_type", ""))),
                        "event_time": _clean_text(row.get("event_time")),
                        "car_sector_adj": float(row["_car"]),
                        "abs_car_sector_adj": float(row["_abs_car"]),
                    }
                    for _, row in clean.head(5).iterrows()
                ],
            }
            item.update(_loo_summary(s))
            split_report["horizons"][f"h{h}"] = item
        report["splits"][split] = split_report
    return report


def write_negative_catalyst_outlier_report(path: str | Path, report: dict[str, object]) -> Path:
    lines = [
        "# Biotech Negative Catalyst Outlier Report",
        "",
        "This report uses the frozen negative binary catalyst slice only.",
        "",
        f"- rows: {report.get('rows')}",
        "",
    ]
    for split, split_report in (report.get("splits", {}) or {}).items():
        lines.extend([f"## {split}", "", f"- rows: {split_report.get('rows')}", ""])
        for horizon, item in (split_report.get("horizons", {}) or {}).items():
            lines.extend(
                [
                    f"### {horizon}",
                    "",
                    f"- n: {item.get('n')}",
                    f"- mean: {item.get('mean')}",
                    f"- median: {item.get('median')}",
                    f"- winsorized mean 5/95: {item.get('winsorized_mean_5_95')}",
                    f"- sign accuracy: {item.get('sign_accuracy')}",
                    f"- leave-one-out mean range: {item.get('leave_one_out_min_mean')} to {item.get('leave_one_out_max_mean')}",
                    f"- mean excluding top 1 absolute event: {item.get('mean_excluding_top_1_abs')}",
                    f"- mean excluding top 3 absolute events: {item.get('mean_excluding_top_3_abs')}",
                    f"- top 1 / top 3 absolute share: {item.get('top_1_abs_share')} / {item.get('top_3_abs_share')}",
                    "",
                    "Largest absolute events:",
                ]
            )
            for event in item.get("largest_abs_events", []):
                lines.append(
                    f"- {event.get('event_id')} {event.get('ticker')} {event.get('event_type')} "
                    f"{event.get('event_time')} car={event.get('car_sector_adj')}"
                )
            lines.append("")
    p = ensure_parent(path)
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def build_negative_strategy_trades(
    event_study: str | Path | pd.DataFrame,
    *,
    horizon: int = 1,
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    df = _read_csv(event_study)
    frame = df[df.get("event_status", pd.Series("ok", index=df.index)).fillna("ok").astype(str).str.lower().eq("ok")].copy()
    col = f"car_sector_adj_h{horizon}"
    frame["position"] = -1
    frame["gross_event_return"] = pd.to_numeric(frame.get(col, pd.Series(np.nan, index=frame.index)), errors="coerce").map(_simple_from_log)
    trades = frame[frame["gross_event_return"].notna()].copy()
    if out_path:
        p = ensure_parent(out_path)
        trades.to_csv(p, index=False)
    return trades


def _negative_strategy_summary(trades: pd.DataFrame, *, cost_bps: float) -> dict[str, object]:
    if trades.empty:
        return {"n_trades": 0}
    frame = trades.copy()
    frame["net_event_return"] = frame["position"].astype(float) * pd.to_numeric(frame["gross_event_return"], errors="coerce") - float(cost_bps) / 10000.0
    frame = frame[frame["net_event_return"].notna()].copy()
    if frame.empty:
        return {"n_trades": 0}
    r = frame["net_event_return"].astype(float)
    equity = (1.0 + r).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    return {
        "n_trades": int(len(frame)),
        "mean_net_event_return": float(r.mean()),
        "median_net_event_return": float(r.median()),
        "hit_rate": float((r > 0).mean()),
        "cumulative_net_return": float(equity.iloc[-1] - 1.0),
        "max_drawdown": float(drawdown.min()),
    }


def _control_report(
    *,
    main_event_study: pd.DataFrame,
    analysis_events_path: Path,
    prices_dir: str | Path,
    out_dir: Path,
    benchmark: str,
    horizons: tuple[int, ...],
    seed: int,
    estimation_window: int,
    estimation_gap: int,
    min_estimation_observations: int,
) -> tuple[dict[str, object], dict[str, object]]:
    placebo_random_events = out_dir / "biotech_negative_catalyst_placebo_random_events.csv"
    placebo_shifted_events = out_dir / "biotech_negative_catalyst_placebo_shifted_events.csv"
    random_events, random_diag = make_placebo_events(analysis_events_path, prices_dir, placebo_random_events, n_per_event=1, mode="random", seed=seed)
    shifted_events, shifted_diag = make_placebo_events(analysis_events_path, prices_dir, placebo_shifted_events, n_per_event=1, mode="shift", seed=seed)
    random_study, random_event_diag = _control_event_study(
        events_path=placebo_random_events,
        prices_dir=prices_dir,
        benchmark=benchmark,
        horizons=horizons,
        out_path=out_dir / "biotech_negative_catalyst_placebo_random_event_study.csv",
        estimation_window=estimation_window,
        estimation_gap=estimation_gap,
        min_estimation_observations=min_estimation_observations,
    )
    shifted_study, shifted_event_diag = _control_event_study(
        events_path=placebo_shifted_events,
        prices_dir=prices_dir,
        benchmark=benchmark,
        horizons=horizons,
        out_path=out_dir / "biotech_negative_catalyst_placebo_shifted_event_study.csv",
        estimation_window=estimation_window,
        estimation_gap=estimation_gap,
        min_estimation_observations=min_estimation_observations,
    )

    main_trades = build_negative_strategy_trades(main_event_study, horizon=1)
    random_trades = build_negative_strategy_trades(random_study, horizon=1)
    shifted_trades = build_negative_strategy_trades(shifted_study, horizon=1)
    main_summary = _summarize_returns(main_event_study, label="negative_main", horizons=horizons)
    random_summary = _summarize_returns(random_study, label="negative_random_placebo", horizons=horizons)
    shifted_summary = _summarize_returns(shifted_study, label="negative_shifted_placebo", horizons=horizons)
    main_strategy = _negative_strategy_summary(main_trades, cost_bps=10.0)
    random_strategy = _negative_strategy_summary(random_trades, cost_bps=10.0)
    shifted_strategy = _negative_strategy_summary(shifted_trades, cost_bps=10.0)
    placebo = {
        "random_events": int(len(random_events)),
        "shifted_events": int(len(shifted_events)),
        "random_generation_diagnostics": random_diag.to_dict(),
        "shifted_generation_diagnostics": shifted_diag.to_dict(),
        "random_event_study_diagnostics": random_event_diag,
        "shifted_event_study_diagnostics": shifted_event_diag,
        "main_summary": main_summary,
        "random_summary": random_summary,
        "shifted_summary": shifted_summary,
        "main_short_strategy": main_strategy,
        "random_short_strategy": random_strategy,
        "shifted_short_strategy": shifted_strategy,
        "random_weaker_than_main_h1": (random_strategy.get("mean_net_event_return") or -np.inf) < (main_strategy.get("mean_net_event_return") or np.inf),
        "shifted_weaker_than_main_h1": (shifted_strategy.get("mean_net_event_return") or -np.inf) < (main_strategy.get("mean_net_event_return") or np.inf),
    }

    peer_events_path = out_dir / "biotech_negative_catalyst_peer_events.csv"
    peer_events, peer_diag = make_peer_control_events(analysis_events_path, peer_events_path)
    peer_study, peer_event_diag = _control_event_study(
        events_path=peer_events_path,
        prices_dir=prices_dir,
        benchmark=benchmark,
        horizons=horizons,
        out_path=out_dir / "biotech_negative_catalyst_peer_event_study.csv",
        estimation_window=estimation_window,
        estimation_gap=estimation_gap,
        min_estimation_observations=min_estimation_observations,
    )
    peer_trades = build_negative_strategy_trades(peer_study, horizon=1)
    peer_strategy = _negative_strategy_summary(peer_trades, cost_bps=10.0)
    peer = {
        "peer_events": int(len(peer_events)),
        "generation_diagnostics": peer_diag.to_dict(),
        "event_study_diagnostics": peer_event_diag,
        "summary": _summarize_returns(peer_study, label="negative_peer_control", horizons=horizons),
        "short_strategy": peer_strategy,
        "weaker_than_main_h1": (peer_strategy.get("mean_net_event_return") or -np.inf) < (main_strategy.get("mean_net_event_return") or np.inf),
        "warning": "Peer controls rotate to another ticker in the biotech negative-catalyst universe; they are not hand-curated mechanism peers.",
    }
    return placebo, peer


def _concat_sources(paths: Iterable[str | Path | pd.DataFrame | None]) -> pd.DataFrame:
    frames = [_read_csv(path) for path in paths]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _base_lookup(base_rates: pd.DataFrame, split: str, horizon: int) -> dict[str, object]:
    if base_rates.empty:
        return {}
    rows = base_rates[
        base_rates["dataset_split"].astype(str).eq(split)
        & base_rates["group_name"].astype(str).eq("all")
        & base_rates["group_value"].astype(str).eq("all")
        & (pd.to_numeric(base_rates["horizon"], errors="coerce") == int(horizon))
    ]
    if rows.empty:
        return {}
    return rows.iloc[0].to_dict()


def _stress_lookup(execution: dict[str, object], key: str, bps: float) -> dict[str, object]:
    rows = execution.get(key, []) if isinstance(execution, dict) else []
    return next((row for row in rows if float(row.get("all_in_cost_bps", -1)) == float(bps)), {})


def _decision(
    *,
    base_rates: pd.DataFrame,
    outlier: dict[str, object],
    timestamp: pd.DataFrame,
    placebo: dict[str, object],
    peer: dict[str, object],
    execution: dict[str, object],
) -> str:
    if not timestamp.empty and (timestamp.get("timestamp_risk_level", pd.Series(dtype=object)).astype(str) == "high").any():
        return "timestamp issue found"

    fresh_h1 = _base_lookup(base_rates, "fresh", 1)
    fresh_h3 = _base_lookup(base_rates, "fresh", 3)
    if int(fresh_h1.get("n", 0) or 0) < 15:
        return "promising but underpowered"

    fresh_outlier_h1 = (((outlier.get("splits", {}) or {}).get("fresh", {}) or {}).get("horizons", {}) or {}).get("h1", {}) or {}
    if (fresh_outlier_h1.get("top_1_abs_share") is not None and float(fresh_outlier_h1["top_1_abs_share"]) >= 0.35) or (
        fresh_outlier_h1.get("top_3_abs_share") is not None and float(fresh_outlier_h1["top_3_abs_share"]) >= 0.60
    ):
        return "outlier-driven"

    close_100 = _stress_lookup(execution, "stress", 100.0)
    next_open_25 = _stress_lookup(execution, "next_open_stress", 25.0)
    if close_100 and close_100.get("mean_net_event_return") is not None and float(close_100["mean_net_event_return"]) <= 0:
        return "execution unrealistic"
    if next_open_25 and next_open_25.get("mean_net_event_return") is not None and float(next_open_25["mean_net_event_return"]) <= 0:
        return "execution unrealistic"

    fresh_core_ok = (
        fresh_h1.get("median_car_sector_adj") is not None
        and float(fresh_h1["median_car_sector_adj"]) < 0
        and fresh_h3.get("median_car_sector_adj") is not None
        and float(fresh_h3["median_car_sector_adj"]) < 0
        and float(fresh_h1.get("sign_accuracy", 0.0) or 0.0) > 0.50
        and float(fresh_h3.get("sign_accuracy", 0.0) or 0.0) > 0.50
    )
    outlier_ok = (
        fresh_outlier_h1.get("mean_excluding_top_1_abs") is not None
        and float(fresh_outlier_h1["mean_excluding_top_1_abs"]) < 0
        and fresh_outlier_h1.get("mean_excluding_top_3_abs") is not None
        and float(fresh_outlier_h1["mean_excluding_top_3_abs"]) < 0
    )
    controls_ok = bool(placebo.get("random_weaker_than_main_h1") and placebo.get("shifted_weaker_than_main_h1") and peer.get("weaker_than_main_h1"))
    return "negative-catalyst slice fresh-confirmed, continue to final audit" if fresh_core_ok and outlier_ok and controls_ok else "failed confirmation"


def write_negative_catalyst_agent_report(path: str | Path, report: dict[str, object]) -> Path:
    base = report.get("base_rate_summary", {}) or {}
    placebo = report.get("placebo_controls", {}) or {}
    peer = report.get("peer_controls", {}) or {}
    timestamp = report.get("timestamp_summary", {}) or {}
    execution = report.get("execution_summary", {}) or {}
    outlier = report.get("outlier_summary", {}) or {}
    lines = [
        "# Agent 3G Biotech Negative Catalyst Narrow Confirmation",
        "",
        f"Decision: {report.get('decision')}.",
        "",
        "This is a narrow confirmation pass for negative binary biotech catalysts only. It does not change parser labels, tune thresholds, include positive readouts in the primary slice, or graduate a signal.",
        "",
        "## Slice",
        "",
        f"- original negative-catalyst rows: {report.get('event_counts', {}).get('original_rows')}",
        f"- fresh negative-catalyst rows: {report.get('event_counts', {}).get('fresh_rows')}",
        f"- combined negative-catalyst rows: {report.get('event_counts', {}).get('combined_rows')}",
        "",
        "## Base Rates",
        "",
    ]
    for split in ("fresh", "original", "combined"):
        for horizon in ("h1", "h3", "h10"):
            row = ((base.get(split, {}) or {}).get(horizon, {}) or {})
            lines.append(
                f"- {split} {horizon}: n={row.get('n')}, mean={row.get('mean_car_sector_adj')}, "
                f"median={row.get('median_car_sector_adj')}, sign_accuracy={row.get('sign_accuracy')}, "
                f"winsorized_mean={row.get('winsorized_mean_car_sector_adj_5_95')}"
            )
    lines.extend(
        [
            "",
            "## Controls",
            "",
            f"- random placebo weaker than main h1 short rule: {placebo.get('random_weaker_than_main_h1')}",
            f"- shifted placebo weaker than main h1 short rule: {placebo.get('shifted_weaker_than_main_h1')}",
            f"- rotated peer weaker than main h1 short rule: {peer.get('weaker_than_main_h1')}",
            f"- main h1 short mean net, 10 bps all-in: {(placebo.get('main_short_strategy', {}) or {}).get('mean_net_event_return')}",
            f"- random h1 short mean net, 10 bps all-in: {(placebo.get('random_short_strategy', {}) or {}).get('mean_net_event_return')}",
            f"- shifted h1 short mean net, 10 bps all-in: {(placebo.get('shifted_short_strategy', {}) or {}).get('mean_net_event_return')}",
            f"- peer h1 short mean net, 10 bps all-in: {(peer.get('short_strategy', {}) or {}).get('mean_net_event_return')}",
            "",
            "## Timestamp Safety",
            "",
            f"- rows audited: {timestamp.get('rows')}",
            f"- high-risk timestamp rows: {timestamp.get('high_risk_rows')}",
            f"- medium-risk timestamp rows: {timestamp.get('medium_risk_rows')}",
            f"- reaction start before expected first tradable window: {timestamp.get('reaction_start_before_expected_rows')}",
            "",
            "## Execution And Outliers",
            "",
            f"- close-to-close 100 bps mean net: {execution.get('close_to_close_100bps_mean_net')}",
            f"- next-open 25 bps mean net: {execution.get('next_open_25bps_mean_net')}",
            f"- fresh h1 top 1 absolute share: {outlier.get('fresh_h1_top_1_abs_share')}",
            f"- fresh h1 top 3 absolute share: {outlier.get('fresh_h1_top_3_abs_share')}",
            f"- fresh h1 mean excluding top 1 absolute: {outlier.get('fresh_h1_mean_excluding_top_1_abs')}",
            f"- fresh h1 mean excluding top 3 absolute: {outlier.get('fresh_h1_mean_excluding_top_3_abs')}",
            "",
            "## Calibration",
            "",
            "Calibration is not applicable in Agent 3G because no probability model is trained. This pass intentionally uses a preregistered rule/base-rate slice after Agent 3E showed the broad probability model was poorly calibrated.",
            "",
            "## Interpretation",
            "",
        ]
    )
    for warning in report.get("warnings", []):
        lines.append(f"- {warning}")
    p = ensure_parent(path)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def run_biotech_negative_catalyst_confirmation(
    *,
    original_event_study_path: str | Path = "artifacts/biotech_catalyst_event_study.csv",
    fresh_event_study_path: str | Path = "artifacts/biotech_catalyst_fresh_event_study.csv",
    original_source_documents_path: str | Path | None = "data/events/biotech_catalyst_source_documents.csv",
    fresh_source_documents_path: str | Path | None = "data/events/biotech_catalyst_fresh_source_documents.csv",
    prices_dir: str | Path = "data/prices/biotech_catalysts",
    out_dir: str | Path = "artifacts",
    benchmark: str = "SPY",
    horizons: tuple[int, ...] = (1, 3, 10),
    seed: int = 777,
    estimation_window: int = 120,
    estimation_gap: int = 5,
    min_estimation_observations: int = 60,
) -> dict[str, object]:
    out = ensure_dir(out_dir)
    event_study_path = out / "biotech_negative_catalyst_event_study.csv"
    base_rates_path = out / "biotech_negative_catalyst_base_rates.csv"
    placebo_report_path = out / "biotech_negative_catalyst_placebo_report.json"
    peer_report_path = out / "biotech_negative_catalyst_peer_report.json"
    outlier_report_path = out / "biotech_negative_catalyst_outlier_report.md"
    execution_report_path = out / "biotech_negative_catalyst_execution_stress.md"
    agent_report_path = out / "biotech_negative_catalyst_agent_3g_report.md"
    analysis_events_path = out / "biotech_negative_catalyst_analysis_events.csv"
    strategy_trades_path = out / "biotech_negative_catalyst_strategy_trades_h1.csv"
    timestamp_path = out / "biotech_negative_catalyst_timestamp_audit.csv"
    next_open_path = out / "biotech_negative_catalyst_next_open_execution_stress.csv"

    event_study = build_negative_catalyst_event_study(
        original_event_study_path,
        fresh_event_study_path,
        out_path=event_study_path,
    )
    if event_study.empty:
        raise ValueError("No negative binary biotech catalysts found in original/fresh event-study artifacts")
    event_study.to_csv(analysis_events_path, index=False)

    base_rates = negative_catalyst_base_rates(event_study, horizons=horizons, out_path=base_rates_path)
    outlier = negative_catalyst_outlier_report(event_study, horizons=horizons)
    write_negative_catalyst_outlier_report(outlier_report_path, outlier)

    placebo, peer = _control_report(
        main_event_study=event_study,
        analysis_events_path=analysis_events_path,
        prices_dir=prices_dir,
        out_dir=out,
        benchmark=benchmark,
        horizons=horizons,
        seed=seed,
        estimation_window=estimation_window,
        estimation_gap=estimation_gap,
        min_estimation_observations=min_estimation_observations,
    )
    _write_json(placebo_report_path, placebo)
    _write_json(peer_report_path, peer)

    trades = build_negative_strategy_trades(event_study, horizon=1, out_path=strategy_trades_path)
    sources = _concat_sources([original_source_documents_path, fresh_source_documents_path])
    timestamp = build_timestamp_audit(event_study, source_documents=sources, prices_dir=prices_dir, out_path=timestamp_path)
    execution = build_execution_stress_report(
        trades,
        timestamp_audit=timestamp,
        prices_dir=prices_dir,
        out_path=execution_report_path,
        next_open_out_path=next_open_path,
        cost_bps_values=(5.0, 25.0, 50.0, 100.0),
    )

    base_summary: dict[str, dict[str, dict[str, object]]] = {}
    for split in ("fresh", "original", "combined"):
        base_summary[split] = {}
        for h in horizons:
            base_summary[split][f"h{h}"] = _base_lookup(base_rates, split, h)

    fresh_h1_outlier = (((outlier.get("splits", {}) or {}).get("fresh", {}) or {}).get("horizons", {}) or {}).get("h1", {}) or {}
    close_100 = _stress_lookup(execution, "stress", 100.0)
    next_open_25 = _stress_lookup(execution, "next_open_stress", 25.0)
    event_counts = {
        "original_rows": int((event_study.get("dataset_split", pd.Series(dtype=object)) == "original").sum()),
        "fresh_rows": int((event_study.get("dataset_split", pd.Series(dtype=object)) == "fresh").sum()),
        "combined_rows": int(len(event_study)),
        "strategy_trades_h1": int(len(trades)),
    }
    report: dict[str, object] = {
        "agent": "3G",
        "domain": "biotech_fda_clinical_catalyst",
        "approach": "preregistered rule/base-rate negative binary catalyst slice; no probability model trained",
        "benchmark": benchmark.upper(),
        "sector_benchmark": "XBI",
        "horizons": list(horizons),
        "event_counts": event_counts,
        "base_rate_summary": base_summary,
        "placebo_controls": placebo,
        "peer_controls": peer,
        "outlier_robustness": outlier,
        "outlier_summary": {
            "fresh_h1_top_1_abs_share": fresh_h1_outlier.get("top_1_abs_share"),
            "fresh_h1_top_3_abs_share": fresh_h1_outlier.get("top_3_abs_share"),
            "fresh_h1_mean_excluding_top_1_abs": fresh_h1_outlier.get("mean_excluding_top_1_abs"),
            "fresh_h1_mean_excluding_top_3_abs": fresh_h1_outlier.get("mean_excluding_top_3_abs"),
        },
        "timestamp_summary": {
            "rows": int(len(timestamp)),
            "high_risk_rows": int((timestamp.get("timestamp_risk_level", pd.Series(dtype=object)).astype(str) == "high").sum()) if not timestamp.empty else 0,
            "medium_risk_rows": int((timestamp.get("timestamp_risk_level", pd.Series(dtype=object)).astype(str) == "medium").sum()) if not timestamp.empty else 0,
            "reaction_start_before_expected_rows": int(timestamp.get("reaction_start_before_expected", pd.Series(dtype=bool)).map(_bool_value).sum()) if not timestamp.empty else 0,
        },
        "execution_summary": {
            "close_to_close_100bps_mean_net": close_100.get("mean_net_event_return"),
            "next_open_25bps_mean_net": next_open_25.get("mean_net_event_return"),
            "next_open_trades": execution.get("next_open_trades"),
        },
        "calibration": {
            "applicable": False,
            "reason": "No probability model is trained in this narrow confirmation; Agent 3G uses a rule/base-rate slice because Agent 3E showed the broad model was poorly calibrated.",
        },
        "artifacts": {
            "event_study": str(event_study_path),
            "base_rates": str(base_rates_path),
            "placebo_report": str(placebo_report_path),
            "peer_report": str(peer_report_path),
            "outlier_report": str(outlier_report_path),
            "execution_stress": str(execution_report_path),
            "agent_report": str(agent_report_path),
            "timestamp_audit": str(timestamp_path),
            "next_open_execution_stress": str(next_open_path),
        },
        "warnings": [
            "Do not call the signal graduated.",
            "No parser labels were changed.",
            "Positive clinical readouts and designation-only events are excluded from the primary slice.",
            "Daily OHLC data cannot prove intraday executable fills or trading-halt status.",
        ],
    }
    report["decision"] = _decision(
        base_rates=base_rates,
        outlier=outlier,
        timestamp=timestamp,
        placebo=placebo,
        peer=peer,
        execution=execution,
    )
    if report["decision"] not in NEGATIVE_CATALYST_DECISIONS:
        report["decision"] = "failed confirmation"
    write_negative_catalyst_agent_report(agent_report_path, report)
    _write_json(out / "biotech_negative_catalyst_agent_3g_report.json", report)
    return report
