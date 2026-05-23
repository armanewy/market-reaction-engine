from __future__ import annotations

import json
from math import exp, log
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .backtest import make_peer_control_events, make_placebo_events
from .biotech_audit import build_duplicate_audit, build_execution_stress_report, build_timestamp_audit
from .biotech_falsification import _control_event_study, _simple_from_log, _summarize_returns
from .paths import ensure_dir, ensure_parent
from .prices import load_price_csv


NEGATIVE_CATALYST_DECISIONS = {
    "negative-catalyst slice fresh-confirmed, continue to final audit",
    "promising but underpowered",
    "failed confirmation",
    "execution unrealistic",
    "outlier-driven",
    "timestamp issue found",
}

TIMESTAMP_REPAIR_DECISIONS = {
    "timestamp repair passes, ready for corrected confirmation",
    "underpowered after timestamp repair",
    "timestamp issue invalidates negative catalyst slice",
    "duplicate issue found",
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


def _parse_utc(value: object) -> pd.Timestamp | pd.NaT:
    text = _clean_text(value)
    if not text:
        return pd.NaT
    return pd.to_datetime(text, errors="coerce", utc=True)


def _session_from_eastern(ts: pd.Timestamp | pd.NaT) -> str:
    if pd.isna(ts):
        return "unknown"
    eastern = pd.Timestamp(ts).tz_convert(ZoneInfo("America/New_York"))
    minutes = eastern.hour * 60 + eastern.minute
    if minutes < 9 * 60 + 30:
        return "before_open"
    if minutes < 16 * 60:
        return "intraday"
    return "after_close"


def _eastern_iso(ts: pd.Timestamp | pd.NaT) -> str:
    if pd.isna(ts):
        return ""
    return pd.Timestamp(ts).tz_convert(ZoneInfo("America/New_York")).isoformat()


def _as_date(value: object) -> pd.Timestamp | pd.NaT:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return pd.NaT
    return pd.Timestamp(ts).tz_localize(None).normalize()


def _first_on_or_after(dates: pd.Series | pd.DatetimeIndex, date: pd.Timestamp) -> pd.Timestamp | pd.NaT:
    idx = pd.DatetimeIndex(pd.to_datetime(pd.Series(dates), errors="coerce").dropna()).tz_localize(None).normalize().sort_values()
    if pd.isna(date) or idx.empty:
        return pd.NaT
    pos = idx.searchsorted(pd.Timestamp(date).tz_localize(None).normalize(), side="left")
    if pos >= len(idx):
        return pd.NaT
    return pd.Timestamp(idx[pos])


def _first_after(dates: pd.Series | pd.DatetimeIndex, date: pd.Timestamp) -> pd.Timestamp | pd.NaT:
    idx = pd.DatetimeIndex(pd.to_datetime(pd.Series(dates), errors="coerce").dropna()).tz_localize(None).normalize().sort_values()
    if pd.isna(date) or idx.empty:
        return pd.NaT
    pos = idx.searchsorted(pd.Timestamp(date).tz_localize(None).normalize(), side="right")
    if pos >= len(idx):
        return pd.NaT
    return pd.Timestamp(idx[pos])


def _trading_open_iso(date: pd.Timestamp | pd.NaT) -> str:
    if pd.isna(date):
        return ""
    naive = pd.Timestamp(date).tz_localize(None).normalize() + pd.Timedelta(hours=9, minutes=30)
    return naive.tz_localize(ZoneInfo("America/New_York")).isoformat()


def _price_return_window(prices: pd.DataFrame, start: pd.Timestamp, horizon: int, *, column: str = "adj_close") -> float:
    prices = prices.sort_values("date").reset_index(drop=True)
    idx = prices.index[prices["date"].eq(pd.Timestamp(start).tz_localize(None).normalize())]
    if len(idx) == 0:
        return float("nan")
    pos = int(idx[0])
    if pos < 1 or pos + int(horizon) - 1 >= len(prices):
        return float("nan")
    prev = float(prices.loc[pos - 1, column])
    end = float(prices.loc[pos + int(horizon) - 1, column])
    if prev <= 0 or end <= 0:
        return float("nan")
    return float(log(end / prev))


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


def _source_repair_groups(source_documents: pd.DataFrame) -> dict[str, dict[str, object]]:
    if source_documents.empty or "event_id" not in source_documents.columns:
        return {}
    groups: dict[str, dict[str, object]] = {}
    for event_id, group in source_documents.groupby(source_documents["event_id"].astype(str), dropna=False):
        times = [_parse_utc(v) for v in group.get("event_time", pd.Series(dtype=object))]
        times = [t for t in times if not pd.isna(t)]
        source_types = sorted({_clean_text(v) for v in group.get("source_type", pd.Series(dtype=object)) if _clean_text(v)})
        exhibit_times = [
            _parse_utc(row.get("event_time"))
            for _, row in group.iterrows()
            if _clean_text(row.get("source_type")) == "sec_exhibit"
        ]
        exhibit_times = [t for t in exhibit_times if not pd.isna(t)]
        groups[str(event_id)] = {
            "source_doc_count": int(len(group)),
            "source_types": source_types,
            "sec_acceptance_time": min(times) if times else pd.NaT,
            "press_release_time": min(exhibit_times) if exhibit_times else pd.NaT,
            "source_url_count": int(group.get("source_url", pd.Series(dtype=object)).dropna().nunique()),
            "source_hash_count": int(group.get("source_hash", pd.Series(dtype=object)).dropna().nunique()),
        }
    return groups


def _first_tradable_for_policy(
    price_dates: pd.Series | pd.DatetimeIndex,
    event_time_utc: pd.Timestamp | pd.NaT,
    release_session: str,
) -> tuple[pd.Timestamp | pd.NaT, list[str]]:
    notes: list[str] = []
    if pd.isna(event_time_utc):
        return pd.NaT, ["missing_selected_event_time"]
    event_date_et = pd.Timestamp(event_time_utc).tz_convert(ZoneInfo("America/New_York")).tz_localize(None).normalize()
    session = _clean_text(release_session).lower()
    if session == "before_open":
        return _first_on_or_after(price_dates, event_date_et), notes
    if session == "after_close":
        return _first_after(price_dates, event_date_et), notes
    if session == "intraday":
        notes.append("intraday_without_intraday_prices_shifted_to_next_trading_day")
        return _first_after(price_dates, event_date_et), notes
    return pd.NaT, ["unknown_release_session"]


def build_negative_catalyst_timestamp_repair_audit(
    event_study: str | Path | pd.DataFrame,
    *,
    source_documents: str | Path | pd.DataFrame | None = None,
    prices_dir: str | Path = "data/prices/biotech_catalysts",
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    """Build a strict timestamp repair audit for the frozen negative-catalyst slice."""
    events = _read_csv(event_study)
    sources = _read_csv(source_documents)
    source_groups = _source_repair_groups(sources)
    price_cache: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, object]] = []
    for _, row in events.iterrows():
        event_id = _clean_text(row.get("event_id"))
        ticker = _clean_text(row.get("ticker")).upper()
        source_info = source_groups.get(event_id, {})
        sec_time = source_info.get("sec_acceptance_time", pd.NaT)
        press_time = source_info.get("press_release_time", pd.NaT)
        fallback_time = _parse_utc(row.get("event_time"))
        selected_time = sec_time if not pd.isna(sec_time) else fallback_time
        selected_source = "sec_acceptance_time" if not pd.isna(sec_time) else "event_time_original"
        release_session = _session_from_eastern(selected_time)
        timestamp_notes: list[str] = []
        timestamp_confidence = "high" if not pd.isna(sec_time) else "low"
        if not pd.isna(press_time):
            timestamp_notes.append("press_release_time_not_separate_from_sec_exhibit_acceptance")
        if selected_source == "event_time_original":
            timestamp_notes.append("missing_sec_source_timestamp")

        first_tradable = pd.NaT
        price_status = "ok"
        try:
            prices = price_cache.setdefault(ticker, load_price_csv(prices_dir, ticker))
            first_tradable, policy_notes = _first_tradable_for_policy(prices["date"], selected_time, release_session)
            timestamp_notes.extend(policy_notes)
            if release_session == "intraday" and timestamp_confidence == "high":
                timestamp_confidence = "medium"
        except Exception as exc:
            price_status = f"price_lookup_failed:{exc}"
            timestamp_notes.append(price_status)
            timestamp_confidence = "low"

        original_reaction_start = _as_date(row.get("reaction_start"))
        original_before_first = bool(
            not pd.isna(original_reaction_start)
            and not pd.isna(first_tradable)
            and original_reaction_start < first_tradable
        )
        if original_before_first:
            timestamp_notes.append("original_reaction_window_started_before_first_tradable")

        ambiguous = bool(pd.isna(selected_time) or pd.isna(first_tradable) or timestamp_confidence == "low")
        model_eligible = not ambiguous
        exclusion_reasons: list[str] = []
        if ambiguous:
            exclusion_reasons.append("timestamp_ambiguous")
        if price_status != "ok":
            exclusion_reasons.append("price_lookup_failed")

        rows.append(
            {
                "event_id": event_id,
                "ticker": ticker,
                "dataset_split": _clean_text(row.get("dataset_split")),
                "biotech_catalyst_event_type": _clean_text(row.get("biotech_catalyst_event_type", row.get("event_type"))),
                "event_time_original": _clean_text(row.get("event_time")),
                "original_reaction_window_start": "" if pd.isna(original_reaction_start) else original_reaction_start.date().isoformat(),
                "sec_acceptance_time": "" if pd.isna(sec_time) else sec_time.isoformat(),
                "press_release_time": "" if pd.isna(press_time) else press_time.isoformat(),
                "source_publication_time": "" if pd.isna(sec_time) else sec_time.isoformat(),
                "selected_event_time": "" if pd.isna(selected_time) else selected_time.isoformat(),
                "selected_event_time_source": selected_source,
                "release_session": release_session,
                "first_tradable_timestamp": _trading_open_iso(first_tradable),
                "reaction_window_start": "" if pd.isna(first_tradable) else first_tradable.date().isoformat(),
                "timestamp_confidence": timestamp_confidence,
                "timestamp_notes": ";".join(timestamp_notes) if timestamp_notes else "none",
                "original_reaction_window_before_first_tradable": original_before_first,
                "timestamp_ambiguous": ambiguous,
                "model_eligible": model_eligible,
                "model_exclusion_reason": ";".join(exclusion_reasons),
                "source_doc_count": int(source_info.get("source_doc_count", 0) or 0),
                "source_types": ";".join(source_info.get("source_types", [])) if source_info else "",
                "source_url_count": int(source_info.get("source_url_count", 0) or 0),
                "source_hash_count": int(source_info.get("source_hash_count", 0) or 0),
            }
        )
    out = pd.DataFrame(rows)
    if out_path:
        p = ensure_parent(out_path)
        out.to_csv(p, index=False)
    return out


def _duplicate_repair_flags(events: pd.DataFrame, duplicate_audit: pd.DataFrame) -> pd.DataFrame:
    if duplicate_audit.empty:
        out = events.copy()
        out["duplicate_key"] = ""
        out["duplicate_group_size"] = 1
        out["duplicate_canonical_event_id"] = out.get("event_id", pd.Series("", index=out.index)).astype(str)
        out["duplicate_model_exclusion_flag"] = False
        out["duplicate_notes"] = "none"
        return out

    dup = duplicate_audit[["event_id", "duplicate_key", "same_key_event_count", "duplicate_risk_level", "duplicate_findings"]].copy()
    out = events.merge(dup, on="event_id", how="left")
    out["duplicate_key"] = out["duplicate_key"].fillna("")
    out["duplicate_group_size"] = pd.to_numeric(out["same_key_event_count"], errors="coerce").fillna(1).astype(int)
    out = out.drop(columns=["same_key_event_count"])
    canonical: dict[str, str] = {}
    for key, group in out.groupby(out["duplicate_key"].where(out["duplicate_key"].astype(str).ne(""), out["event_id"].astype(str)), dropna=False):
        ordered = group.sort_values(["selected_event_time", "event_id"], kind="mergesort")
        canonical[str(key)] = _clean_text(ordered.iloc[0]["event_id"])
    out["duplicate_canonical_event_id"] = [
        canonical.get(_clean_text(row.get("duplicate_key")) or _clean_text(row.get("event_id")), _clean_text(row.get("event_id")))
        for _, row in out.iterrows()
    ]
    out["duplicate_model_exclusion_flag"] = (out["duplicate_group_size"] > 1) & (out["event_id"].astype(str) != out["duplicate_canonical_event_id"].astype(str))
    out["duplicate_notes"] = out.get("duplicate_findings", pd.Series("none", index=out.index)).fillna("none").astype(str)
    return out


def build_negative_catalyst_repaired_events(
    event_study: str | Path | pd.DataFrame,
    timestamp_audit: str | Path | pd.DataFrame,
    duplicate_audit: str | Path | pd.DataFrame,
    *,
    prices_dir: str | Path = "data/prices/biotech_catalysts",
    horizons: Iterable[int] = (1, 3, 10),
    sector_benchmark: str = "XBI",
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    events = _read_csv(event_study)
    audit = _read_csv(timestamp_audit)
    dup = _read_csv(duplicate_audit)
    if events.empty or audit.empty:
        out = pd.DataFrame()
        if out_path:
            ensure_parent(out_path).write_text("", encoding="utf-8")
        return out

    merged = events.merge(audit, on=["event_id", "ticker"], how="inner", suffixes=("", "_timestamp_audit"))
    merged = _duplicate_repair_flags(merged, dup)
    merged["model_eligible"] = merged["model_eligible"].map(_bool_value) & ~merged["duplicate_model_exclusion_flag"].map(_bool_value)
    reasons = merged.get("model_exclusion_reason", pd.Series("", index=merged.index)).fillna("").astype(str)
    duplicate_reason = np.where(merged["duplicate_model_exclusion_flag"].map(_bool_value), "duplicate_non_canonical", "")
    merged["model_exclusion_reason"] = [
        ";".join(part for part in [reason, dup_reason] if part)
        for reason, dup_reason in zip(reasons, duplicate_reason, strict=False)
    ]

    eligible = merged[merged["model_eligible"].map(_bool_value)].copy()
    price_cache: dict[str, pd.DataFrame] = {}
    xbi = load_price_csv(prices_dir, sector_benchmark)
    for h in horizons:
        values = []
        simple_values = []
        sector_values = []
        for _, row in eligible.iterrows():
            start = _as_date(row.get("reaction_window_start"))
            ticker = _clean_text(row.get("ticker")).upper()
            try:
                px = price_cache.setdefault(ticker, load_price_csv(prices_dir, ticker))
                stock_ret = _price_return_window(px, start, int(h))
                sector_ret = _price_return_window(xbi, start, int(h))
                car = stock_ret - sector_ret if pd.notna(stock_ret) and pd.notna(sector_ret) else np.nan
            except Exception:
                stock_ret = np.nan
                sector_ret = np.nan
                car = np.nan
            values.append(car)
            simple_values.append(_simple_from_log(car))
            sector_values.append(sector_ret)
        eligible[f"timestamp_repaired_sector_return_h{h}"] = sector_values
        eligible[f"timestamp_repaired_car_sector_adj_h{h}"] = values
        eligible[f"timestamp_repaired_car_sector_adj_simple_h{h}"] = simple_values

    if out_path:
        p = ensure_parent(out_path)
        eligible.to_csv(p, index=False)
    return eligible


def _descriptive_return_summary(events: pd.DataFrame, *, horizons: Iterable[int] = (1, 3, 10)) -> dict[str, object]:
    out: dict[str, object] = {}
    frames = [("combined", events)]
    if "dataset_split" in events.columns:
        frames.extend((str(split), group.copy()) for split, group in events.groupby(events["dataset_split"].fillna("unknown").astype(str), dropna=False))
    for split, frame in frames:
        item: dict[str, object] = {"rows": int(len(frame))}
        for h in horizons:
            col = f"timestamp_repaired_car_sector_adj_h{h}"
            s = pd.to_numeric(frame.get(col, pd.Series(dtype=float)), errors="coerce").dropna()
            item[f"h{h}"] = {
                "n": int(len(s)),
                "mean": float(s.mean()) if len(s) else None,
                "median": float(s.median()) if len(s) else None,
                "sign_accuracy": float((s < 0).mean()) if len(s) else None,
                "winsorized_mean_5_95": _winsorized_mean(s),
            }
        out[split] = item
    return out


def _timestamp_repair_decision(report: dict[str, object]) -> str:
    if int(report.get("duplicate_rows", 0) or 0) > 0:
        return "duplicate issue found"
    if int(report.get("repaired_eligible_rows", 0) or 0) < 45 or int(report.get("fresh_repaired_eligible_rows", 0) or 0) < 20:
        return "underpowered after timestamp repair"
    if int(report.get("likely_oos_predictions_after_repair", 0) or 0) < 20:
        return "underpowered after timestamp repair"
    if int(report.get("unrepaired_pre_window_leakage_rows", 0) or 0) > 0 or int(report.get("ambiguous_timestamp_rows", 0) or 0) > 0:
        return "timestamp issue invalidates negative catalyst slice"
    return "timestamp repair passes, ready for corrected confirmation"


def write_negative_catalyst_timestamp_repair_report(path: str | Path, report: dict[str, object]) -> Path:
    returns = report.get("descriptive_returns", {}) or {}
    lines = [
        "# Agent 3I Biotech Negative Catalyst Timestamp Repair",
        "",
        f"Decision: {report.get('decision')}.",
        "",
        "This is a timestamp repair and audit pass for the frozen negative binary biotech catalyst slice. It does not train a model, tune thresholds, or change parser labels.",
        "",
        "## Timestamp Repair",
        "",
        f"- total rows: {report.get('total_rows')}",
        f"- repaired eligible rows: {report.get('repaired_eligible_rows')}",
        f"- fresh repaired eligible rows: {report.get('fresh_repaired_eligible_rows')}",
        f"- original repaired eligible rows: {report.get('original_repaired_eligible_rows')}",
        f"- original pre-window leakage rows found: {report.get('original_pre_window_leakage_rows')}",
        f"- rows repaired by shifting to first tradable window: {report.get('rows_repaired_by_window_shift')}",
        f"- rows dropped for unrepaired pre-window leakage: {report.get('unrepaired_pre_window_leakage_rows')}",
        f"- ambiguous timestamp rows: {report.get('ambiguous_timestamp_rows')}",
        f"- duplicate rows: {report.get('duplicate_rows')}",
        f"- likely OOS predictions after repair, min_train={report.get('min_train')}: {report.get('likely_oos_predictions_after_repair')}",
        "",
        "## Descriptive Returns",
        "",
    ]
    for split in ("fresh", "original", "combined"):
        item = returns.get(split, {}) or {}
        for horizon in ("h1", "h3", "h10"):
            row = item.get(horizon, {}) or {}
            lines.append(
                f"- {split} {horizon}: n={row.get('n')}, mean={row.get('mean')}, "
                f"median={row.get('median')}, sign_accuracy={row.get('sign_accuracy')}, "
                f"winsorized_mean={row.get('winsorized_mean_5_95')}"
            )
    lines.extend(
        [
            "",
            "## Policy",
            "",
            "- before_open uses the same trading day when available.",
            "- after_close uses the next trading day.",
            "- intraday rows are conservatively shifted to the next trading day because local data is daily OHLC only.",
            "- Rows with missing source timestamps or no first-tradable trading day are not model eligible.",
            "- Duplicate non-canonical rows are not model eligible.",
            "",
            "No signal is graduated from this timestamp repair pass.",
        ]
    )
    p = ensure_parent(path)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def run_biotech_negative_catalyst_timestamp_repair(
    *,
    original_event_study_path: str | Path = "artifacts/biotech_catalyst_event_study.csv",
    fresh_event_study_path: str | Path = "artifacts/biotech_catalyst_fresh_event_study.csv",
    original_source_documents_path: str | Path | None = "data/events/biotech_catalyst_source_documents.csv",
    fresh_source_documents_path: str | Path | None = "data/events/biotech_catalyst_fresh_source_documents.csv",
    prices_dir: str | Path = "data/prices/biotech_catalysts",
    out_dir: str | Path = "artifacts",
    horizons: tuple[int, ...] = (1, 3, 10),
    min_train: int = 40,
    sector_benchmark: str = "XBI",
) -> dict[str, object]:
    out = ensure_dir(out_dir)
    event_study_path = out / "biotech_negative_catalyst_event_study.csv"
    repaired_events_path = out / "biotech_negative_catalyst_timestamp_repaired_events.csv"
    timestamp_audit_path = out / "biotech_negative_catalyst_timestamp_audit.csv"
    duplicate_audit_path = out / "biotech_negative_catalyst_duplicate_audit.csv"
    report_path = out / "biotech_negative_catalyst_agent_3i_report.md"
    json_path = out / "biotech_negative_catalyst_agent_3i_report.json"

    event_study = build_negative_catalyst_event_study(
        original_event_study_path,
        fresh_event_study_path,
        out_path=event_study_path,
    )
    if event_study.empty:
        raise ValueError("No negative binary biotech catalyst rows found for timestamp repair")
    sources = _concat_sources([original_source_documents_path, fresh_source_documents_path])
    timestamp_audit = build_negative_catalyst_timestamp_repair_audit(
        event_study,
        source_documents=sources,
        prices_dir=prices_dir,
        out_path=timestamp_audit_path,
    )
    duplicate_audit = build_duplicate_audit(event_study, source_documents=sources, out_path=duplicate_audit_path)
    repaired = build_negative_catalyst_repaired_events(
        event_study,
        timestamp_audit,
        duplicate_audit,
        prices_dir=prices_dir,
        horizons=horizons,
        sector_benchmark=sector_benchmark,
        out_path=repaired_events_path,
    )

    audit_eligible = timestamp_audit[timestamp_audit["model_eligible"].map(_bool_value)].copy()
    duplicate_rows = int(repaired.get("duplicate_model_exclusion_flag", pd.Series(dtype=bool)).map(_bool_value).sum()) if not repaired.empty else 0
    unrepaired_pre_window = int(
        timestamp_audit[
            timestamp_audit["original_reaction_window_before_first_tradable"].map(_bool_value)
            & ~timestamp_audit["model_eligible"].map(_bool_value)
        ].shape[0]
    )
    report: dict[str, object] = {
        "agent": "3I",
        "domain": "biotech_fda_clinical_catalyst",
        "total_rows": int(len(timestamp_audit)),
        "repaired_eligible_rows": int(len(repaired)),
        "fresh_repaired_eligible_rows": int((repaired.get("dataset_split", pd.Series(dtype=object)).astype(str) == "fresh").sum()) if not repaired.empty else 0,
        "original_repaired_eligible_rows": int((repaired.get("dataset_split", pd.Series(dtype=object)).astype(str) == "original").sum()) if not repaired.empty else 0,
        "original_pre_window_leakage_rows": int(timestamp_audit["original_reaction_window_before_first_tradable"].map(_bool_value).sum()),
        "rows_repaired_by_window_shift": int(timestamp_audit["original_reaction_window_before_first_tradable"].map(_bool_value).sum()),
        "unrepaired_pre_window_leakage_rows": unrepaired_pre_window,
        "ambiguous_timestamp_rows": int(timestamp_audit["timestamp_ambiguous"].map(_bool_value).sum()),
        "duplicate_rows": duplicate_rows,
        "likely_oos_predictions_after_repair": max(0, int(len(repaired)) - int(min_train)),
        "min_train": int(min_train),
        "descriptive_returns": _descriptive_return_summary(repaired, horizons=horizons),
        "artifacts": {
            "repaired_events": str(repaired_events_path),
            "timestamp_audit": str(timestamp_audit_path),
            "duplicate_audit": str(duplicate_audit_path),
            "agent_report": str(report_path),
        },
        "warnings": [
            "Do not train a model from this timestamp repair pass.",
            "No parser labels were changed.",
            "Corrected confirmation must rerun placebo and peer controls on the repaired event set.",
        ],
    }
    # Keep this for audit transparency even though it is not a gate.
    report["timestamp_model_eligible_rows_before_duplicate_filter"] = int(len(audit_eligible))
    report["decision"] = _timestamp_repair_decision(report)
    if report["decision"] not in TIMESTAMP_REPAIR_DECISIONS:
        report["decision"] = "timestamp issue invalidates negative catalyst slice"
    write_negative_catalyst_timestamp_repair_report(report_path, report)
    _write_json(json_path, report)
    return report


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
