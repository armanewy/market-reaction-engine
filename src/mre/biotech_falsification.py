from __future__ import annotations

import json
from math import exp, sqrt
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, balanced_accuracy_score, brier_score_loss, log_loss, roc_auc_score

from .backtest import (
    calibration_table,
    make_peer_control_events,
    make_placebo_events,
    null_shuffle_strategy_test,
    simulate_event_strategy,
)
from .event_study import run_event_study
from .modeling import available_features, load_event_study, make_direction_pipeline, prepare_feature_frame
from .paths import ensure_dir, ensure_parent


BIOTECH_DECISION_OPTIONS = {
    "promising, require fresh-data confirmation",
    "underpowered",
    "failed falsification",
    "parser/context issue found",
    "timestamp/leakage issue found",
}

NEGATIVE_H3_EVENT_TYPES = {
    "fda_complete_response_letter",
    "trial_halt",
    "endpoint_failure",
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
        if np.isnan(value):
            return None
        return float(value)
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


def _simple_from_log(value: object) -> float:
    try:
        x = float(value)
    except Exception:
        return float("nan")
    if np.isnan(x):
        return float("nan")
    return float(exp(x) - 1.0)


def _market_cap_bucket(value: object) -> str:
    cap = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(cap):
        return "unknown"
    if cap < 300_000_000:
        return "micro_lt_300m"
    if cap < 2_000_000_000:
        return "small_300m_2b"
    if cap < 10_000_000_000:
        return "mid_2b_10b"
    return "large_gt_10b"


def prepare_biotech_falsification_events(
    events: str | Path | pd.DataFrame,
    *,
    sector_benchmark: str = "XBI",
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    """Build the reviewed event-study input without mutating parser artifacts."""
    df = pd.read_csv(events) if not isinstance(events, pd.DataFrame) else events.copy()
    if df.empty:
        out = df.copy()
    else:
        review_status = df.get("review_status", pd.Series("", index=df.index)).fillna("").astype(str).str.lower().str.strip()
        event_type = df.get("biotech_catalyst_event_type", df.get("event_subtype", pd.Series("", index=df.index))).fillna("").astype(str).str.lower().str.strip()
        drop_reason = df.get("drop_reason", pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
        out = df[
            review_status.isin({"reviewed", "curated", "approved"})
            & event_type.ne("")
            & event_type.ne("unknown")
            & drop_reason.eq("")
        ].copy()

    if out.empty:
        raise ValueError("No reviewed usable biotech catalyst events found for falsification")

    biotech_type = out["biotech_catalyst_event_type"].fillna("").astype(str).str.lower().str.strip()
    out["event_type"] = biotech_type
    out["event_subtype"] = biotech_type
    out["event_family"] = "biotech_fda_clinical_catalyst"
    out["summary"] = out.get("summary", pd.Series("", index=out.index)).fillna("").astype(str)
    out["summary"] = out["summary"].where(out["summary"].str.strip().ne(""), out["ticker"].astype(str) + " " + biotech_type + " biotech catalyst")
    out["sector_benchmark"] = out.get("sector_benchmark", pd.Series("", index=out.index)).fillna("").astype(str).str.upper().str.strip()
    out.loc[out["sector_benchmark"].isin({"", "NAN", "NONE", "UNKNOWN"}), "sector_benchmark"] = sector_benchmark.upper()
    out["surprise_direction"] = out.get("event_direction_pre_price", pd.Series("unknown", index=out.index)).fillna("unknown").astype(str).str.lower().str.strip()
    out["expectedness"] = out.get("expectedness", pd.Series("unknown", index=out.index)).fillna("unknown").astype(str).str.lower().str.strip()
    out["surprise_magnitude"] = out.get("surprise_magnitude", pd.Series("unknown", index=out.index)).fillna("unknown").astype(str).str.lower().str.strip()
    if "materiality" not in out.columns:
        out["materiality"] = 0.5
    out["materiality"] = pd.to_numeric(out["materiality"], errors="coerce").fillna(0.5).clip(0.0, 1.0)

    out["primary_endpoint_met"] = out.get("endpoint_met", pd.Series("", index=out.index)).map(
        lambda v: "true" if _bool_value(v) else ("unknown" if _clean_text(v) == "" else "false")
    )
    out["safety_signal"] = np.where(_bool_series(out, "safety_negative_flag"), "negative", "none")
    out["market_cap_bucket"] = out.get("market_cap_before_event", pd.Series(np.nan, index=out.index)).map(_market_cap_bucket)
    out["biotech_binary_catalyst"] = np.where(_bool_series(out, "binary_catalyst_flag"), "true", "false")
    out["biotech_designation_only"] = np.where(_bool_series(out, "designation_only_flag"), "true", "false")
    out["biotech_regulatory_decision"] = np.where(_bool_series(out, "regulatory_decision_flag"), "true", "false")
    out["biotech_clinical_readout"] = np.where(_bool_series(out, "clinical_trial_readout_flag"), "true", "false")

    if out_path:
        p = ensure_parent(out_path)
        out.to_csv(p, index=False)
    return out.reset_index(drop=True)


def _sector_target_direction(car: pd.Series, flat_threshold: float = 0.002) -> pd.Series:
    values = pd.to_numeric(car, errors="coerce")
    return np.select([values > flat_threshold, values < -flat_threshold], ["up", "down"], default="flat")


def add_sector_targets(event_study: pd.DataFrame, horizons: Iterable[int] = (1, 3, 10)) -> pd.DataFrame:
    out = event_study.copy()
    for h in horizons:
        car = pd.to_numeric(out.get(f"car_sector_adj_h{h}", pd.Series(np.nan, index=out.index)), errors="coerce")
        out[f"target_positive_sector_h{h}"] = car > 0
        out[f"target_direction_sector_h{h}"] = _sector_target_direction(car)
        out[f"car_sector_adj_simple_h{h}"] = out.get(f"car_sector_adj_simple_h{h}", car.map(_simple_from_log))
    return out


def _modeling_frame_for_sector(df: pd.DataFrame, horizon: int) -> tuple[pd.DataFrame, pd.Series]:
    car = f"car_sector_adj_h{horizon}"
    required = ["event_status", car]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns for sector walk-forward: {missing}")
    clean = df[(df["event_status"] == "ok") & pd.to_numeric(df[car], errors="coerce").notna()].copy()
    if clean.empty:
        raise ValueError("No usable event-study rows with sector-adjusted returns")
    clean = prepare_feature_frame(clean)
    y = (pd.to_numeric(clean[car], errors="coerce") > 0).astype(int)
    return clean, y


def purged_walk_forward_sector_model(
    event_study: str | Path | pd.DataFrame,
    *,
    horizon: int = 1,
    min_train: int = 40,
    purge_days: int | None = None,
    out_predictions: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    purge_days = int(horizon if purge_days is None else purge_days)
    df = load_event_study(event_study) if not isinstance(event_study, pd.DataFrame) else event_study.copy()
    frame, y = _modeling_frame_for_sector(df, horizon)
    date_col = "reaction_start" if "reaction_start" in frame.columns else "event_time"
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    order = frame[date_col].sort_values(kind="mergesort").index
    frame = frame.loc[order].reset_index(drop=True)
    y = y.loc[order].reset_index(drop=True)
    min_train = max(2, int(min_train))
    if len(frame) <= min_train:
        raise ValueError(f"Need more than min_train={min_train} usable events for walk-forward validation")

    rows: list[dict[str, object]] = []
    car = f"car_sector_adj_h{horizon}"
    for i in range(min_train, len(frame)):
        test_date = pd.Timestamp(frame.iloc[i][date_col])
        cutoff = test_date - pd.Timedelta(days=purge_days)
        train_mask = frame.iloc[:i][date_col] < cutoff
        X_train = frame.iloc[:i].loc[train_mask].copy()
        y_train = y.iloc[:i].loc[train_mask].copy()
        X_one = frame.iloc[[i]].copy()
        base_rate = float(y.iloc[:i].mean())
        if len(X_train) < min_train:
            status = "skipped_not_enough_purged_train"
            proba = np.nan
            pred = np.nan
        elif y_train.nunique() < 2:
            status = "fallback_base_rate_one_class_train"
            proba = float(np.clip(y_train.mean(), 1e-6, 1.0 - 1e-6))
            pred = int(proba >= 0.5)
        else:
            model = make_direction_pipeline(X_train)
            model.fit(X_train, y_train)
            proba = float(model.predict_proba(X_one)[:, 1][0])
            pred = int(proba >= 0.5)
            status = "ok"
        row = frame.iloc[i]
        rows.append(
            {
                "row_number": i,
                "event_id": row.get("event_id", ""),
                "ticker": row.get("ticker", ""),
                "reaction_start": row.get("reaction_start", ""),
                "event_time": row.get("event_time", ""),
                "event_type": row.get("event_type", ""),
                "biotech_catalyst_event_type": row.get("biotech_catalyst_event_type", row.get("event_type", "")),
                "event_direction_pre_price": row.get("event_direction_pre_price", row.get("surprise_direction", "")),
                "trial_phase": row.get("trial_phase", ""),
                "market_cap_bucket": row.get("market_cap_bucket", ""),
                "binary_catalyst_flag": row.get("binary_catalyst_flag", ""),
                "designation_only_flag": row.get("designation_only_flag", ""),
                "clinical_trial_readout_flag": row.get("clinical_trial_readout_flag", ""),
                "regulatory_decision_flag": row.get("regulatory_decision_flag", ""),
                "y_true": int(y.iloc[i]),
                "actual_positive": int(y.iloc[i]),
                "predicted_positive_probability": proba,
                "predicted_positive": pred,
                "baseline_positive_probability": float(np.clip(base_rate, 1e-6, 1.0 - 1e-6)),
                "model_status": status,
                "purge_days": purge_days,
                "train_rows_after_purge": int(len(X_train)),
                car: row.get(car, np.nan),
                f"car_sector_adj_simple_h{horizon}": row.get(f"car_sector_adj_simple_h{horizon}", np.nan),
                f"car_market_model_h{horizon}": row.get(f"car_market_model_h{horizon}", np.nan),
                f"car_index_adj_h{horizon}": row.get(f"car_index_adj_h{horizon}", np.nan),
                f"raw_return_h{horizon}": row.get(f"raw_return_h{horizon}", np.nan),
            }
        )

    pred_df = pd.DataFrame(rows)
    eval_df = pred_df[pred_df["predicted_positive_probability"].notna()].copy()
    report: dict[str, object] = {
        "horizon": int(horizon),
        "target": car,
        "min_train": int(min_train),
        "purge_days": int(purge_days),
        "n_events": int(len(frame)),
        "n_predictions": int(len(eval_df)),
        "n_skipped": int(len(pred_df) - len(eval_df)),
        "categorical_features": available_features(frame)[0],
        "numeric_features": available_features(frame)[1],
        "warnings": ["First biotech falsification pass only; do not treat walk-forward metrics as a graduated signal."],
    }
    if not eval_df.empty:
        y_true = eval_df["y_true"].astype(int)
        proba = eval_df["predicted_positive_probability"].astype(float).clip(1e-6, 1 - 1e-6)
        pred = eval_df["predicted_positive"].astype(int)
        metrics = {"accuracy": float(accuracy_score(y_true, pred)), "brier_score": float(brier_score_loss(y_true, proba))}
        if y_true.nunique() == 2:
            metrics.update(
                {
                    "balanced_accuracy": float(balanced_accuracy_score(y_true, pred)),
                    "roc_auc": float(roc_auc_score(y_true, proba)),
                    "log_loss": float(log_loss(y_true, proba, labels=[0, 1])),
                }
            )
        report["metrics"] = metrics
    else:
        report["metrics"] = {}

    if out_predictions:
        p = ensure_parent(out_predictions)
        pred_df.to_csv(p, index=False)
        report["predictions_path"] = str(p)
    return pred_df, report


def _summarize_returns(df: pd.DataFrame, *, label: str, horizons: Iterable[int] = (1, 3, 10)) -> dict[str, object]:
    out: dict[str, object] = {"label": label, "rows": int(len(df))}
    ok = df[df.get("event_status", "ok").astype(str).eq("ok")].copy() if "event_status" in df.columns else df.copy()
    out["ok_rows"] = int(len(ok))
    for h in horizons:
        col = f"car_sector_adj_h{h}"
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
        col = f"car_sector_adj_h{h}"
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
                "mean_car_sector_adj": float(s.mean()),
                "median_car_sector_adj": float(s.median()),
                "std_car_sector_adj": float(s.std(ddof=1)) if len(s) > 1 else np.nan,
                "stderr_car_sector_adj": float(s.std(ddof=1) / sqrt(len(s))) if len(s) > 1 else np.nan,
                "mean_simple_sector_adj": float(simple.mean()),
                "median_simple_sector_adj": float(simple.median()),
                "mean_abs_car_sector_adj": float(s.abs().mean()),
            }
        )


def biotech_base_rate_table(
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
        "biotech_catalyst_event_type",
        "event_direction_pre_price",
        "binary_catalyst_flag",
        "clinical_trial_readout_flag",
        "regulatory_decision_flag",
        "designation_only_flag",
        "trial_phase",
        "market_cap_bucket",
    ]
    for col in group_cols:
        if col not in frame.columns:
            continue
        keys = frame[col].fillna("unknown").astype(str).str.lower().str.strip()
        for value, group in frame.groupby(keys, dropna=False):
            _append_group_summary(rows, group, group_name=col, group_value=str(value), horizons=horizons)
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["horizon", "group_name", "n", "mean_car_sector_adj"], ascending=[True, True, False, False]).reset_index(drop=True)
    if out_path:
        p = ensure_parent(out_path)
        out.to_csv(p, index=False)
    return out


def _hypothesis_masks(df: pd.DataFrame) -> dict[str, tuple[pd.Series, str, str]]:
    event_type = df.get("biotech_catalyst_event_type", df.get("event_type", pd.Series("", index=df.index))).fillna("").astype(str).str.lower().str.strip()
    direction = df.get("event_direction_pre_price", df.get("surprise_direction", pd.Series("", index=df.index))).fillna("").astype(str).str.lower().str.strip()
    runup = pd.to_numeric(df.get("pre_event_market_adjusted_return_20d", pd.Series(np.nan, index=df.index)), errors="coerce")
    endpoint_met = _bool_series(df, "endpoint_met")
    safety_negative = _bool_series(df, "safety_negative_flag")
    return {
        "h1_negative_binary_catalyst": (
            _bool_series(df, "binary_catalyst_flag") & direction.eq("negative"),
            "negative",
            "binary_catalyst_flag=true and event_direction_pre_price=negative",
        ),
        "h2_positive_clinical_readout": (
            _bool_series(df, "clinical_trial_readout_flag") & endpoint_met & ~safety_negative,
            "positive",
            "clinical_trial_readout_flag=true, endpoint_met=true, safety_negative_flag=false",
        ),
        "h3_crl_halt_endpoint_failure": (
            event_type.isin(NEGATIVE_H3_EVENT_TYPES) | _bool_series(df, "trial_failure_flag"),
            "negative",
            "CRL, trial halt, endpoint failure, or trial_failure_flag=true",
        ),
        "h4_designation_only": (
            _bool_series(df, "designation_only_flag"),
            "weaker_noisier",
            "designation_only_flag=true",
        ),
        "h5_positive_after_runup": (
            direction.eq("positive") & (runup > 0),
            "weaker_or_sell_the_news",
            "event_direction_pre_price=positive and pre_event_market_adjusted_return_20d>0",
        ),
    }


def evaluate_biotech_hypotheses(event_study: pd.DataFrame, *, horizons: Iterable[int] = (1, 3, 10)) -> dict[str, object]:
    ok = event_study[event_study.get("event_status", "ok").astype(str).eq("ok")].copy() if "event_status" in event_study.columns else event_study.copy()
    out: dict[str, object] = {}
    for name, (mask, expected, definition) in _hypothesis_masks(ok).items():
        subset = ok[mask.fillna(False)].copy()
        item: dict[str, object] = {"definition": definition, "expected": expected, "n": int(len(subset))}
        for h in horizons:
            s = pd.to_numeric(subset.get(f"car_sector_adj_h{h}", pd.Series(dtype=float)), errors="coerce").dropna()
            if s.empty:
                item[f"h{h}"] = {"n": 0}
                continue
            if expected == "positive":
                aligned = s > 0
            elif expected == "negative":
                aligned = s < 0
            else:
                aligned = pd.Series([np.nan] * len(s))
            item[f"h{h}"] = {
                "n": int(len(s)),
                "mean_log": float(s.mean()),
                "median_log": float(s.median()),
                "mean_simple": float(s.map(_simple_from_log).mean()),
                "positive_rate": float((s > 0).mean()),
                "negative_rate": float((s < 0).mean()),
                "alignment_rate": float(aligned.mean()) if expected in {"positive", "negative"} else None,
                "mean_abs_log": float(s.abs().mean()),
            }
        out[name] = item
    return out


def simulate_source_direction_strategy(
    event_study: pd.DataFrame,
    *,
    horizon: int = 1,
    cost_bps: float = 5.0,
    slippage_bps: float = 5.0,
) -> tuple[pd.DataFrame, dict[str, object]]:
    frame = event_study[event_study.get("event_status", "ok").astype(str).eq("ok")].copy()
    car = f"car_sector_adj_h{horizon}"
    direction = frame.get("event_direction_pre_price", frame.get("surprise_direction", pd.Series("", index=frame.index))).fillna("").astype(str).str.lower().str.strip()
    frame["position"] = np.select([direction.eq("positive"), direction.eq("negative")], [1, -1], default=0)
    frame["gross_event_return"] = pd.to_numeric(frame.get(car, pd.Series(np.nan, index=frame.index)), errors="coerce").map(_simple_from_log)
    round_trip_cost = (float(cost_bps) + float(slippage_bps)) / 10000.0
    frame["trade_cost"] = np.where(frame["position"] != 0, round_trip_cost, 0.0)
    frame["net_event_return"] = frame["position"] * frame["gross_event_return"] - frame["trade_cost"]
    trades = frame[(frame["position"] != 0) & frame["net_event_return"].notna()].copy()
    if trades.empty:
        return trades, {"horizon": horizon, "n_trades": 0, "warning": "No positive/negative source-direction trades."}
    r = trades["net_event_return"].astype(float)
    equity = (1.0 + r).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    report = {
        "horizon": int(horizon),
        "return_column": car,
        "n_trades": int(len(trades)),
        "n_long": int((trades["position"] == 1).sum()),
        "n_short": int((trades["position"] == -1).sum()),
        "cost_bps": float(cost_bps),
        "slippage_bps": float(slippage_bps),
        "mean_net_event_return": float(r.mean()),
        "median_net_event_return": float(r.median()),
        "hit_rate": float((r > 0).mean()),
        "cumulative_net_return": float(equity.iloc[-1] - 1.0),
        "max_drawdown": float(drawdown.min()),
        "long_mean_net_event_return": float(trades.loc[trades["position"] == 1, "net_event_return"].mean()) if (trades["position"] == 1).any() else None,
        "short_mean_net_event_return": float(trades.loc[trades["position"] == -1, "net_event_return"].mean()) if (trades["position"] == -1).any() else None,
    }
    return trades, report


def _market_cap_sensitivity(event_study: pd.DataFrame, *, horizons: Iterable[int] = (1, 3, 10)) -> dict[str, object]:
    if "market_cap_bucket" not in event_study.columns:
        return {}
    out: dict[str, object] = {}
    frame = event_study[event_study.get("event_status", "ok").astype(str).eq("ok")].copy()
    for bucket, group in frame.groupby(event_study["market_cap_bucket"].fillna("unknown").astype(str), dropna=False):
        out[str(bucket)] = _summarize_returns(group, label=str(bucket), horizons=horizons)
    return out


def _outlier_concentration(event_study: pd.DataFrame, *, horizon: int = 1) -> dict[str, object]:
    frame = event_study[event_study.get("event_status", "ok").astype(str).eq("ok")].copy()
    car = pd.to_numeric(frame.get(f"car_sector_adj_h{horizon}", pd.Series(dtype=float)), errors="coerce")
    frame = frame[car.notna()].copy()
    if frame.empty:
        return {"horizon": int(horizon), "n": 0}
    frame["_abs_car"] = car.loc[frame.index].abs()
    frame["_signed_car"] = car.loc[frame.index]
    frame = frame.sort_values("_abs_car", ascending=False)
    total_abs = float(frame["_abs_car"].sum())
    top = frame.head(5).copy()
    trimmed = frame.iloc[1:].copy()
    return {
        "horizon": int(horizon),
        "n": int(len(frame)),
        "mean_car_sector_adj": float(frame["_signed_car"].mean()),
        "median_car_sector_adj": float(frame["_signed_car"].median()),
        "top_abs_event_share": float(top.iloc[0]["_abs_car"] / total_abs) if total_abs > 0 else None,
        "top_5_abs_event_share": float(top["_abs_car"].sum() / total_abs) if total_abs > 0 else None,
        "mean_excluding_largest_abs_event": float(trimmed["_signed_car"].mean()) if len(trimmed) else None,
        "largest_abs_events": [
            {
                "event_id": str(row.get("event_id", "")),
                "ticker": str(row.get("ticker", "")),
                "biotech_catalyst_event_type": str(row.get("biotech_catalyst_event_type", row.get("event_type", ""))),
                "event_direction_pre_price": str(row.get("event_direction_pre_price", "")),
                "market_cap_bucket": str(row.get("market_cap_bucket", "")),
                "car_sector_adj": float(row["_signed_car"]),
                "abs_car_sector_adj": float(row["_abs_car"]),
            }
            for _, row in top.iterrows()
        ],
    }


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
    study = add_sector_targets(study, horizons=horizons)
    ensure_parent(out_path)
    study.to_csv(out_path, index=False)
    return study, {"events_total": diag.events_total, "events_ok": diag.events_ok, "events_skipped": diag.events_skipped, "skipped_reasons": diag.skipped_reasons}


def _decision(report: dict[str, object]) -> str:
    walk = report.get("walk_forward", {})
    metrics = walk.get("metrics", {}) if isinstance(walk, dict) else {}
    calibration = report.get("calibration", {})
    strategy = report.get("strategy", {})
    null = report.get("null_shuffle", {})
    hypotheses = report.get("hypotheses", {})
    placebo = report.get("placebo_controls", {})
    peer = report.get("peer_controls", {})

    n_predictions = int(walk.get("n_predictions", 0)) if isinstance(walk, dict) else 0
    if n_predictions < 30:
        return "underpowered"

    roc_auc = metrics.get("roc_auc") if isinstance(metrics, dict) else None
    ece = calibration.get("expected_calibration_error") if isinstance(calibration, dict) else None
    mean_net = strategy.get("mean_net_event_return") if isinstance(strategy, dict) else None
    null_p = null.get("one_sided_p_value_actual_ge_null") if isinstance(null, dict) else None
    h1 = hypotheses.get("h1_negative_binary_catalyst", {}) if isinstance(hypotheses, dict) else {}
    h2 = hypotheses.get("h2_positive_clinical_readout", {}) if isinstance(hypotheses, dict) else {}
    h4 = hypotheses.get("h4_designation_only", {}) if isinstance(hypotheses, dict) else {}
    h1_align = (h1.get("h1", {}) or {}).get("alignment_rate") if isinstance(h1, dict) else None
    h2_align = (h2.get("h1", {}) or {}).get("alignment_rate") if isinstance(h2, dict) else None
    binary_abs = (report.get("base_rate_contrasts", {}) or {}).get("binary_mean_abs_h1")
    designation_abs = (h4.get("h1", {}) or {}).get("mean_abs_log") if isinstance(h4, dict) else None
    placebo_weaker = bool(placebo.get("random_weaker_than_main_h1", False) and placebo.get("shifted_weaker_than_main_h1", False)) if isinstance(placebo, dict) else False
    peer_weaker = bool(peer.get("weaker_than_main_h1", False)) if isinstance(peer, dict) else False

    promising = (
        roc_auc is not None
        and float(roc_auc) > 0.60
        and ece is not None
        and float(ece) <= 0.20
        and mean_net is not None
        and float(mean_net) > 0
        and null_p is not None
        and float(null_p) <= 0.10
        and placebo_weaker
        and peer_weaker
        and h1_align is not None
        and float(h1_align) > 0.50
        and h2_align is not None
        and float(h2_align) > 0.50
        and binary_abs is not None
        and designation_abs is not None
        and float(designation_abs) < float(binary_abs)
    )
    if promising:
        return "promising, require fresh-data confirmation"
    return "failed falsification"


def write_biotech_agent_3d_report(path: str | Path, report: dict[str, object]) -> Path:
    lines = [
        "# Agent 3D Biotech Catalyst First Falsification Pass",
        "",
        f"Decision: {report.get('decision', 'unknown')}.",
        "",
        "This is a first falsification pass only. It is not a graduated signal, trading recommendation, or final empirical result.",
        "",
        "## Inputs",
        "",
        f"- reviewed usable event rows: {report.get('event_counts', {}).get('analysis_events')}",
        f"- event-study ok rows: {report.get('event_study_diagnostics', {}).get('events_ok')}",
        f"- benchmark: {report.get('benchmark')}",
        f"- sector benchmark: {report.get('sector_benchmark')}",
        f"- horizons: {', '.join(str(h) for h in report.get('horizons', []))}",
        "",
        "## Walk-Forward And Costs",
        "",
    ]
    walk = report.get("walk_forward", {}) or {}
    metrics = walk.get("metrics", {}) or {}
    calibration = report.get("calibration", {}) or {}
    strategy = report.get("strategy", {}) or {}
    null = report.get("null_shuffle", {}) or {}
    lines.extend(
        [
            f"- predictions: {walk.get('n_predictions')}",
            f"- ROC AUC: {metrics.get('roc_auc')}",
            f"- accuracy: {metrics.get('accuracy')}",
            f"- brier score: {metrics.get('brier_score')}",
            f"- ECE: {calibration.get('expected_calibration_error')}",
            f"- strategy trades: {strategy.get('n_trades')}",
            f"- strategy long / short: {strategy.get('n_long')} / {strategy.get('n_short')}",
            f"- mean net event return: {strategy.get('mean_net_event_return')}",
            f"- cumulative net return: {strategy.get('cumulative_net_return')}",
            f"- null-shuffle p-value: {null.get('one_sided_p_value_actual_ge_null')}",
            "",
            "## Hypothesis Checks",
            "",
        ]
    )
    for name, item in (report.get("hypotheses", {}) or {}).items():
        h1 = item.get("h1", {}) if isinstance(item, dict) else {}
        h3 = item.get("h3", {}) if isinstance(item, dict) else {}
        h10 = item.get("h10", {}) if isinstance(item, dict) else {}
        lines.append(
            f"- {name}: n={item.get('n')}, h1_mean={h1.get('mean_log')}, h1_alignment={h1.get('alignment_rate')}, "
            f"h3_mean={h3.get('mean_log')}, h10_mean={h10.get('mean_log')}"
        )
    lines.extend(["", "## Controls", ""])
    placebo = report.get("placebo_controls", {}) or {}
    peer = report.get("peer_controls", {}) or {}
    lines.extend(
        [
            f"- random placebo h1 mean: {(placebo.get('random_summary', {}) or {}).get('h1', {}).get('mean_log')}",
            f"- shifted placebo h1 mean: {(placebo.get('shifted_summary', {}) or {}).get('h1', {}).get('mean_log')}",
            f"- peer-control h1 mean: {(peer.get('summary', {}) or {}).get('h1', {}).get('mean_log')}",
            f"- source-direction fixed strategy h1 mean net return: {(report.get('source_direction_strategy', {}) or {}).get('h1', {}).get('mean_net_event_return')}",
            "",
            "## Secondary Sector And Outliers",
            "",
        ]
    )
    secondary = report.get("secondary_sector_control", {}) or {}
    secondary_summary = secondary.get("summary", {}) if isinstance(secondary, dict) else {}
    outliers = report.get("outlier_concentration", {}) or {}
    lines.extend(
        [
            f"- IBB secondary h1 mean: {(secondary_summary.get('h1', {}) or {}).get('mean_log')}",
            f"- IBB secondary status: {secondary.get('status', 'ok') if isinstance(secondary, dict) else 'unknown'}",
            f"- largest absolute h1 event share: {outliers.get('top_abs_event_share')}",
            f"- top five absolute h1 event share: {outliers.get('top_5_abs_event_share')}",
            f"- h1 mean excluding largest absolute event: {outliers.get('mean_excluding_largest_abs_event')}",
            "",
            "## Interpretation",
            "",
        ]
    )
    for warning in report.get("warnings", []):
        lines.append(f"- {warning}")
    lines.extend(
        [
            "",
            "Do not graduate this signal from Agent 3D. A positive result would require fresh-data confirmation, stronger peer controls, timestamp audit, and repeated preregistered validation.",
        ]
    )
    p = ensure_parent(path)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def run_biotech_catalyst_falsification_pass(
    *,
    events_path: str | Path = "data/events/biotech_catalyst_review_queue.csv",
    features_path: str | Path | None = "data/events/biotech_catalyst_features.csv",
    prices_dir: str | Path = "data/prices/biotech_catalysts",
    out_dir: str | Path = "artifacts",
    benchmark: str = "SPY",
    sector_benchmark: str = "XBI",
    horizons: tuple[int, ...] = (1, 3, 10),
    min_train: int = 40,
    purge_days: int = 3,
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
    analysis_events_path = out / "biotech_catalyst_analysis_events.csv"
    event_study_path = out / "biotech_catalyst_event_study.csv"
    base_rates_path = out / "biotech_catalyst_base_rates.csv"
    predictions_path = out / "biotech_catalyst_walk_forward_predictions.csv"
    backtest_report_path = out / "biotech_catalyst_backtest_report.json"
    placebo_report_path = out / "biotech_catalyst_placebo_report.json"
    peer_report_path = out / "biotech_catalyst_peer_report.json"
    null_report_path = out / "biotech_catalyst_null_shuffle_report.json"
    agent_report_path = out / "biotech_catalyst_agent_3d_report.md"

    analysis_events = prepare_biotech_falsification_events(events_path, sector_benchmark=sector_benchmark, out_path=analysis_events_path)
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
    secondary_sector_control: dict[str, object] = {}
    secondary_sector = "IBB"
    secondary_price_path = Path(prices_dir) / f"{secondary_sector}.csv"
    if secondary_sector.upper() != sector_benchmark.upper() and secondary_price_path.exists():
        secondary_events_path = out / "biotech_catalyst_analysis_events_ibb.csv"
        secondary_events = analysis_events.copy()
        secondary_events["sector_benchmark"] = secondary_sector
        secondary_events.to_csv(secondary_events_path, index=False)
        secondary_study_path = out / "biotech_catalyst_event_study_ibb.csv"
        secondary_study, secondary_diag = _control_event_study(
            events_path=secondary_events_path,
            prices_dir=prices_dir,
            benchmark=benchmark,
            horizons=horizons,
            out_path=secondary_study_path,
            estimation_window=estimation_window,
            estimation_gap=estimation_gap,
            min_estimation_observations=min_estimation_observations,
        )
        secondary_sector_control = {
            "sector_benchmark": secondary_sector,
            "event_study": str(secondary_study_path),
            "diagnostics": secondary_diag,
            "summary": _summarize_returns(secondary_study, label="secondary_ibb", horizons=horizons),
            "hypotheses": evaluate_biotech_hypotheses(secondary_study, horizons=horizons),
        }
    else:
        secondary_sector_control = {
            "sector_benchmark": secondary_sector,
            "status": "not_run",
            "reason": f"{secondary_price_path} not found" if secondary_sector.upper() != sector_benchmark.upper() else "primary sector benchmark is already IBB",
        }
    base_rates = biotech_base_rate_table(event_study, horizons=horizons, out_path=base_rates_path)
    predictions, walk_report = purged_walk_forward_sector_model(
        event_study,
        horizon=1,
        min_train=min_train,
        purge_days=purge_days,
        out_predictions=predictions_path,
    )
    usable_preds = predictions[predictions["predicted_positive_probability"].notna()].copy()
    calibration_path = out / "biotech_catalyst_calibration.csv"
    _, calibration_report = calibration_table(usable_preds, bins=10, out_path=calibration_path)
    trades_path = out / "biotech_catalyst_strategy_trades.csv"
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
    null_distribution_path = out / "biotech_catalyst_null_shuffle_distribution.csv"
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

    source_direction: dict[str, object] = {}
    for h in horizons:
        source_trades, source_report = simulate_source_direction_strategy(event_study, horizon=h, cost_bps=cost_bps, slippage_bps=slippage_bps)
        source_direction[f"h{h}"] = source_report
        source_trades.to_csv(out / f"biotech_catalyst_source_direction_trades_h{h}.csv", index=False)

    placebo_random_events = out / "biotech_catalyst_placebo_random_events.csv"
    placebo_shifted_events = out / "biotech_catalyst_placebo_shifted_events.csv"
    random_events, random_diag = make_placebo_events(analysis_events_path, prices_dir, placebo_random_events, n_per_event=1, mode="random", seed=seed)
    shifted_events, shifted_diag = make_placebo_events(analysis_events_path, prices_dir, placebo_shifted_events, n_per_event=1, mode="shift", seed=seed)
    random_study, random_event_diag = _control_event_study(
        events_path=placebo_random_events,
        prices_dir=prices_dir,
        benchmark=benchmark,
        horizons=horizons,
        out_path=out / "biotech_catalyst_placebo_random_event_study.csv",
        estimation_window=estimation_window,
        estimation_gap=estimation_gap,
        min_estimation_observations=min_estimation_observations,
    )
    shifted_study, shifted_event_diag = _control_event_study(
        events_path=placebo_shifted_events,
        prices_dir=prices_dir,
        benchmark=benchmark,
        horizons=horizons,
        out_path=out / "biotech_catalyst_placebo_shifted_event_study.csv",
        estimation_window=estimation_window,
        estimation_gap=estimation_gap,
        min_estimation_observations=min_estimation_observations,
    )

    peer_events_path = out / "biotech_catalyst_peer_events.csv"
    peer_events, peer_diag = make_peer_control_events(analysis_events_path, peer_events_path)
    peer_study, peer_event_diag = _control_event_study(
        events_path=peer_events_path,
        prices_dir=prices_dir,
        benchmark=benchmark,
        horizons=horizons,
        out_path=out / "biotech_catalyst_peer_event_study.csv",
        estimation_window=estimation_window,
        estimation_gap=estimation_gap,
        min_estimation_observations=min_estimation_observations,
    )

    main_summary = _summarize_returns(event_study, label="main", horizons=horizons)
    random_summary = _summarize_returns(random_study, label="random_placebo", horizons=horizons)
    shifted_summary = _summarize_returns(shifted_study, label="shifted_placebo", horizons=horizons)
    peer_summary = _summarize_returns(peer_study, label="peer_control", horizons=horizons)
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
        "warning": "Peer controls rotate to another ticker in the same reviewed biotech universe; they are weaker than a hand-built asset/mechanism peer basket.",
    }
    _write_json(placebo_report_path, placebo_report)
    _write_json(peer_report_path, peer_report)
    _write_json(null_report_path, null_report)

    binary_rows = ok[_bool_series(ok, "binary_catalyst_flag")]
    designation_rows = ok[_bool_series(ok, "designation_only_flag")]
    base_rate_contrasts = {
        "binary_n": int(len(binary_rows)),
        "designation_n": int(len(designation_rows)),
        "binary_mean_abs_h1": float(pd.to_numeric(binary_rows.get("car_sector_adj_h1", pd.Series(dtype=float)), errors="coerce").abs().mean()) if len(binary_rows) else None,
        "designation_mean_abs_h1": float(pd.to_numeric(designation_rows.get("car_sector_adj_h1", pd.Series(dtype=float)), errors="coerce").abs().mean()) if len(designation_rows) else None,
    }
    report: dict[str, object] = {
        "agent": "3D",
        "domain": "biotech_fda_clinical_catalyst",
        "benchmark": benchmark.upper(),
        "sector_benchmark": sector_benchmark.upper(),
        "horizons": list(horizons),
        "event_counts": {
            "analysis_events": int(len(analysis_events)),
            "event_study_rows": int(len(event_study)),
            "event_study_ok_rows": int((event_study["event_status"] == "ok").sum()),
            "binary_catalysts": int(_bool_series(analysis_events, "binary_catalyst_flag").sum()),
            "positive_catalysts": int(analysis_events.get("event_direction_pre_price", pd.Series("", index=analysis_events.index)).astype(str).str.lower().eq("positive").sum()),
            "negative_catalysts": int(analysis_events.get("event_direction_pre_price", pd.Series("", index=analysis_events.index)).astype(str).str.lower().eq("negative").sum()),
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
        "secondary_sector_control": secondary_sector_control,
        "market_cap_sensitivity": _market_cap_sensitivity(event_study, horizons=horizons),
        "outlier_concentration": _outlier_concentration(event_study, horizon=1),
        "base_rate_contrasts": base_rate_contrasts,
        "features_path": str(features_path) if features_path else None,
        "artifacts": {
            "analysis_events": str(analysis_events_path),
            "event_study": str(event_study_path),
            "event_study_ibb": secondary_sector_control.get("event_study"),
            "base_rates": str(base_rates_path),
            "walk_forward_predictions": str(predictions_path),
            "calibration": str(calibration_path),
            "strategy_trades": str(trades_path),
            "null_shuffle_distribution": str(null_distribution_path),
            "null_shuffle_report": str(null_report_path),
            "placebo_report": str(placebo_report_path),
            "peer_report": str(peer_report_path),
            "backtest_report": str(backtest_report_path),
            "agent_report": str(agent_report_path),
        },
        "warnings": [
            "Do not call the signal graduated from this first falsification pass.",
            "No parser labels were changed by this run.",
            "The walk-forward classifier targets h1 XBI-adjusted abnormal return direction and uses only pre-event/source-grounded features.",
            "IBB secondary control is optional and is not used for the primary decision unless separately inspected.",
        ],
    }
    report["decision"] = _decision(report)
    if report["decision"] not in BIOTECH_DECISION_OPTIONS:
        report["decision"] = "failed falsification"

    _write_json(backtest_report_path, report)
    write_biotech_agent_3d_report(agent_report_path, report)
    return report
