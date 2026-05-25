from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from math import exp, sqrt
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .events import load_events
from .modeling import available_features, load_event_study, make_direction_pipeline, modeling_frame
from .paths import ensure_dir, ensure_parent
from .prices import load_price_csv


@dataclass
class BacktestDiagnostics:
    rows_total: int = 0
    rows_used: int = 0
    rows_skipped: int = 0
    skipped_reasons: dict[str, int] = field(default_factory=dict)

    def add_skip(self, reason: str, n: int = 1) -> None:
        self.rows_skipped += int(n)
        self.skipped_reasons[reason] = self.skipped_reasons.get(reason, 0) + int(n)

    def to_dict(self) -> dict:
        return asdict(self)


def _as_bool_target(series: pd.Series) -> pd.Series:
    s = series.copy()
    if s.dtype == bool:
        return s.astype(int)
    text = s.astype(str).str.lower().str.strip()
    mapped = text.map({"true": 1, "false": 0, "1": 1, "0": 0, "up": 1, "down": 0, "positive": 1, "negative": 0})
    if mapped.notna().all():
        return mapped.astype(int)
    return pd.to_numeric(s, errors="coerce").fillna(0).astype(int)


def _simple_return_from_row(row: pd.Series, return_column: str) -> float:
    value = row.get(return_column, np.nan)
    try:
        value = float(value)
    except Exception:
        return float("nan")
    if np.isnan(value):
        return float("nan")
    # Columns named car_market_model_h* and car_index_adj_h* are log returns in
    # event_study.py.  Columns ending in _simple_h* and raw_return_h* are simple.
    name = return_column.lower()
    if "_simple" in name or name.startswith("raw_return") or name.startswith("expected_return") or name.startswith("benchmark_return") or name.startswith("sector_return"):
        return value
    return float(exp(value) - 1.0)


def calibration_table(
    predictions: str | Path | pd.DataFrame,
    *,
    probability_column: str = "predicted_positive_probability",
    target_column: str = "y_true",
    bins: int = 10,
    out_path: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Compute equal-width probability calibration bins and ECE."""
    df = pd.read_csv(predictions) if not isinstance(predictions, pd.DataFrame) else predictions.copy()
    missing = [c for c in [probability_column, target_column] if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns for calibration: {missing}")
    clean = df[[probability_column, target_column]].copy()
    clean[probability_column] = pd.to_numeric(clean[probability_column], errors="coerce")
    clean[target_column] = _as_bool_target(clean[target_column])
    clean = clean.dropna(subset=[probability_column])
    clean[probability_column] = clean[probability_column].clip(0.0, 1.0)
    if clean.empty:
        raise ValueError("No usable prediction rows for calibration")
    edges = np.linspace(0.0, 1.0, int(bins) + 1)
    # Include 1.0 in the last bin.
    clean["calibration_bin"] = pd.cut(clean[probability_column], bins=edges, include_lowest=True, right=True)
    rows = []
    ece = 0.0
    for interval, group in clean.groupby("calibration_bin", observed=False):
        n = int(len(group))
        if n == 0:
            rows.append({"bin": str(interval), "n": 0, "mean_probability": np.nan, "observed_rate": np.nan, "abs_error": np.nan})
            continue
        mean_probability = float(group[probability_column].mean())
        observed_rate = float(group[target_column].mean())
        abs_error = abs(mean_probability - observed_rate)
        ece += (n / len(clean)) * abs_error
        rows.append({"bin": str(interval), "n": n, "mean_probability": mean_probability, "observed_rate": observed_rate, "abs_error": abs_error})
    out = pd.DataFrame(rows)
    report = {
        "n_predictions": int(len(clean)),
        "bins": int(bins),
        "expected_calibration_error": float(ece),
        "mean_probability": float(clean[probability_column].mean()),
        "observed_rate": float(clean[target_column].mean()),
    }
    if out_path:
        p = ensure_parent(out_path)
        out.to_csv(p, index=False)
    return out, report


def simulate_event_strategy(
    predictions: str | Path | pd.DataFrame,
    *,
    horizon: int = 1,
    probability_column: str = "predicted_positive_probability",
    return_column: str | None = None,
    long_threshold: float = 0.60,
    short_threshold: float | None = None,
    long_threshold_column: str | None = None,
    short_threshold_column: str | None = None,
    allow_short: bool = False,
    cost_bps: float = 0.0,
    slippage_bps: float = 0.0,
    out_trades: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Simulate a simple event-level strategy from walk-forward probabilities.

    The return is event-level, not annualized.  Costs/slippage are treated as a
    round-trip per-trade deduction in basis points.  The default return column is
    the market-model abnormal return for the requested horizon.
    """
    df = pd.read_csv(predictions) if not isinstance(predictions, pd.DataFrame) else predictions.copy()
    if return_column is None:
        return_column = f"car_market_model_h{horizon}"
    missing = [c for c in [probability_column, return_column] if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns for strategy simulation: {missing}")
    out = df.copy()
    out[probability_column] = pd.to_numeric(out[probability_column], errors="coerce")
    short_threshold = (1.0 - float(long_threshold)) if short_threshold is None else float(short_threshold)
    if long_threshold_column and long_threshold_column not in out.columns:
        raise ValueError(f"Missing long-threshold column for strategy simulation: {long_threshold_column}")
    if short_threshold_column and short_threshold_column not in out.columns:
        raise ValueError(f"Missing short-threshold column for strategy simulation: {short_threshold_column}")
    if long_threshold_column:
        long_values = pd.to_numeric(out[long_threshold_column], errors="coerce").fillna(float(long_threshold))
    else:
        long_values = pd.Series([float(long_threshold)] * len(out), index=out.index)
    if short_threshold_column:
        short_values = pd.to_numeric(out[short_threshold_column], errors="coerce").fillna(float(short_threshold))
    else:
        short_values = pd.Series([float(short_threshold)] * len(out), index=out.index)
    positions = []
    for p, long_value, short_value in zip(out[probability_column], long_values, short_values):
        if pd.isna(p):
            positions.append(0)
        elif p >= float(long_value):
            positions.append(1)
        elif allow_short and p <= float(short_value):
            positions.append(-1)
        else:
            positions.append(0)
    out["position"] = positions
    out["gross_event_return"] = out.apply(lambda row: _simple_return_from_row(row, return_column), axis=1)
    round_trip_cost = (float(cost_bps) + float(slippage_bps)) / 10000.0
    out["trade_cost"] = np.where(out["position"] != 0, round_trip_cost, 0.0)
    out["net_event_return"] = out["position"] * pd.to_numeric(out["gross_event_return"], errors="coerce") - out["trade_cost"]
    trades = out[(out["position"] != 0) & out["net_event_return"].notna()].copy()
    if "reaction_start" in trades.columns:
        trades["reaction_start"] = pd.to_datetime(trades["reaction_start"], errors="coerce")
        trades = trades.sort_values("reaction_start").reset_index(drop=True)
    else:
        trades = trades.reset_index(drop=True)
    if trades.empty:
        report = {
            "horizon": int(horizon),
            "n_predictions": int(len(out)),
            "n_trades": 0,
            "long_threshold": float(long_threshold),
            "short_threshold": float(short_threshold),
            "long_threshold_column": long_threshold_column,
            "short_threshold_column": short_threshold_column,
            "allow_short": bool(allow_short),
            "cost_bps": float(cost_bps),
            "slippage_bps": float(slippage_bps),
            "warning": "No trades met the threshold.",
        }
    else:
        r = pd.to_numeric(trades["net_event_return"], errors="coerce").dropna()
        gross = pd.to_numeric(trades["gross_event_return"], errors="coerce").dropna()
        equity = (1.0 + r).cumprod()
        drawdown = equity / equity.cummax() - 1.0
        report = {
            "horizon": int(horizon),
            "n_predictions": int(len(out)),
            "n_trades": int(len(trades)),
            "n_long": int((trades["position"] == 1).sum()),
            "n_short": int((trades["position"] == -1).sum()),
            "long_threshold": float(long_threshold),
            "short_threshold": float(short_threshold),
            "long_threshold_column": long_threshold_column,
            "short_threshold_column": short_threshold_column,
            "allow_short": bool(allow_short),
            "cost_bps": float(cost_bps),
            "slippage_bps": float(slippage_bps),
            "mean_gross_event_return": float(gross.mean()),
            "mean_net_event_return": float(r.mean()),
            "median_net_event_return": float(r.median()),
            "hit_rate": float((r > 0).mean()),
            "event_sharpe": float(r.mean() / r.std(ddof=1) * sqrt(len(r))) if len(r) > 1 and r.std(ddof=1) > 0 else None,
            "cumulative_net_return": float(equity.iloc[-1] - 1.0),
            "max_drawdown": float(drawdown.min()),
            "avg_trade_cost": float(trades["trade_cost"].mean()),
        }
    if out_trades:
        p = ensure_parent(out_trades)
        trades.to_csv(p, index=False)
        report["trades_path"] = str(p)
    return trades, report


def select_threshold_from_prior_predictions(
    prior_predictions: pd.DataFrame,
    *,
    candidate_thresholds: Iterable[float],
    default_threshold: float = 0.60,
    min_threshold_selection_rows: int = 30,
    horizon: int = 1,
    probability_column: str = "predicted_positive_probability",
    return_column: str | None = None,
    allow_short: bool = False,
    cost_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> dict[str, object]:
    prior = prior_predictions.copy()
    clean = prior[pd.to_numeric(prior.get(probability_column, pd.Series(dtype=float)), errors="coerce").notna()].copy()
    if len(clean) < int(min_threshold_selection_rows):
        return {
            "long_threshold": float(default_threshold),
            "short_threshold": float(1.0 - default_threshold),
            "status": "default_not_enough_prior_rows",
            "prior_rows": int(len(clean)),
            "metric": None,
        }
    candidates = sorted({float(v) for v in candidate_thresholds})
    if not candidates:
        candidates = [float(default_threshold)]
    rows: list[dict[str, object]] = []
    for threshold in candidates:
        _, report = simulate_event_strategy(
            clean,
            horizon=horizon,
            probability_column=probability_column,
            return_column=return_column,
            long_threshold=threshold,
            allow_short=allow_short,
            cost_bps=cost_bps,
            slippage_bps=slippage_bps,
        )
        metric = report.get("mean_net_event_return")
        rows.append(
            {
                "threshold": threshold,
                "short_threshold": float(1.0 - threshold),
                "metric": float(metric) if metric is not None and not pd.isna(metric) else None,
                "n_trades": int(report.get("n_trades", 0) or 0),
            }
        )
    usable = [row for row in rows if row["metric"] is not None and int(row["n_trades"]) > 0]
    if not usable:
        return {
            "long_threshold": float(default_threshold),
            "short_threshold": float(1.0 - default_threshold),
            "status": "default_no_candidate_trades",
            "prior_rows": int(len(clean)),
            "metric": None,
            "candidate_results": rows,
        }
    best = max(usable, key=lambda row: (float(row["metric"]), int(row["n_trades"]), -float(row["threshold"])))
    return {
        "long_threshold": float(best["threshold"]),
        "short_threshold": float(best["short_threshold"]),
        "status": "selected_from_prior",
        "prior_rows": int(len(clean)),
        "metric": float(best["metric"]),
        "candidate_results": rows,
    }


def apply_nested_expanding_thresholds(
    predictions: pd.DataFrame,
    *,
    candidate_thresholds: Iterable[float],
    default_threshold: float = 0.60,
    min_threshold_selection_rows: int = 30,
    horizon: int = 1,
    probability_column: str = "predicted_positive_probability",
    return_column: str | None = None,
    allow_short: bool = False,
    cost_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> tuple[pd.DataFrame, dict[str, object]]:
    out = predictions.copy().reset_index(drop=True)
    selected_long: list[float] = []
    selected_short: list[float] = []
    statuses: list[str] = []
    prior_rows: list[int] = []
    selected_metrics: list[float | None] = []
    for i in range(len(out)):
        selection = select_threshold_from_prior_predictions(
            out.iloc[:i],
            candidate_thresholds=candidate_thresholds,
            default_threshold=default_threshold,
            min_threshold_selection_rows=min_threshold_selection_rows,
            horizon=horizon,
            probability_column=probability_column,
            return_column=return_column,
            allow_short=allow_short,
            cost_bps=cost_bps,
            slippage_bps=slippage_bps,
        )
        selected_long.append(float(selection["long_threshold"]))
        selected_short.append(float(selection["short_threshold"]))
        statuses.append(str(selection["status"]))
        prior_rows.append(int(selection["prior_rows"]))
        metric = selection.get("metric")
        selected_metrics.append(float(metric) if metric is not None and not pd.isna(metric) else None)
    out["selected_long_threshold"] = selected_long
    out["selected_short_threshold"] = selected_short
    out["threshold_selection_status"] = statuses
    out["threshold_selection_prior_rows"] = prior_rows
    out["threshold_selection_metric"] = selected_metrics
    status_counts = {str(k): int(v) for k, v in out["threshold_selection_status"].value_counts(dropna=False).items()}
    threshold_counts = {str(k): int(v) for k, v in out["selected_long_threshold"].value_counts(dropna=False).sort_index().items()}
    report = {
        "threshold_mode": "nested_expanding",
        "candidate_thresholds": [float(v) for v in sorted({float(v) for v in candidate_thresholds})],
        "default_threshold": float(default_threshold),
        "min_threshold_selection_rows": int(min_threshold_selection_rows),
        "rows_using_default_threshold": int(out["threshold_selection_status"].astype(str).str.startswith("default_").sum()),
        "selected_threshold_summary": threshold_counts,
        "selection_status_counts": status_counts,
    }
    return out, report


def concentration_diagnostics(
    trades_or_predictions_df: pd.DataFrame,
    *,
    return_column: str = "net_event_return",
    group_columns: tuple[str, ...] = ("ticker", "event_type"),
    top_n: int = 20,
) -> dict[str, object]:
    """Summarize whether event returns are concentrated in a few issuers.

    The diagnostic is descriptive only; it does not change strategy returns or
    promotion gates.  Contributions are measured by absolute event return so a
    large loser and a large winner both count as concentration risk.
    """
    df = trades_or_predictions_df.copy()
    warnings: list[str] = []
    report: dict[str, object] = {
        "n_rows": int(len(df)),
        "n_unique_tickers": int(df["ticker"].nunique()) if "ticker" in df.columns else 0,
        "return_column": return_column,
        "top_1_ticker_share_by_abs_return": 0.0,
        "top_3_ticker_share_by_abs_return": 0.0,
        "top_5_ticker_share_by_abs_return": 0.0,
        "per_ticker": [],
        "groups": {},
        "warnings": warnings,
    }
    if df.empty:
        warnings.append("No rows available for concentration diagnostics.")
        return report
    if return_column not in df.columns:
        warnings.append(f"Return column {return_column!r} is absent; concentration by return was not computed.")
        return report

    returns = pd.to_numeric(df[return_column], errors="coerce").fillna(0.0)
    df = df.copy()
    df["_return_contribution"] = returns
    df["_abs_return_contribution"] = returns.abs()
    total_abs = float(df["_abs_return_contribution"].sum())

    def group_summary(column: str) -> list[dict[str, object]]:
        grouped = (
            df.groupby(column, dropna=False)
            .agg(
                n_rows=("_abs_return_contribution", "size"),
                return_contribution=("_return_contribution", "sum"),
                abs_return_contribution=("_abs_return_contribution", "sum"),
            )
            .reset_index()
        )
        grouped["abs_return_share"] = grouped["abs_return_contribution"] / total_abs if total_abs > 0 else 0.0
        grouped = grouped.sort_values(["abs_return_contribution", "n_rows"], ascending=[False, False]).head(int(top_n))
        rows: list[dict[str, object]] = []
        for _, row in grouped.iterrows():
            rows.append(
                {
                    str(column): "" if pd.isna(row[column]) else str(row[column]),
                    "n_rows": int(row["n_rows"]),
                    "return_contribution": float(row["return_contribution"]),
                    "abs_return_contribution": float(row["abs_return_contribution"]),
                    "abs_return_share": float(row["abs_return_share"]),
                }
            )
        return rows

    if "ticker" in df.columns:
        ticker_rows = group_summary("ticker")
        report["per_ticker"] = ticker_rows
        ticker_shares = [float(row["abs_return_share"]) for row in ticker_rows]
        report["top_1_ticker_share_by_abs_return"] = float(sum(ticker_shares[:1]))
        report["top_3_ticker_share_by_abs_return"] = float(sum(ticker_shares[:3]))
        report["top_5_ticker_share_by_abs_return"] = float(sum(ticker_shares[:5]))
        if int(report["n_unique_tickers"]) <= 1:
            warnings.append("All rows are from one ticker; issuer concentration is maximal.")
        top_5_share = float(report["top_5_ticker_share_by_abs_return"])
        if top_5_share > 0.75:
            warnings.append("Top 5 tickers contribute more than 75% of absolute event return.")
        elif top_5_share > 0.50:
            warnings.append("Top 5 tickers contribute more than 50% of absolute event return.")
    else:
        warnings.append("ticker column is absent; issuer concentration was not computed.")

    group_reports: dict[str, list[dict[str, object]]] = {}
    for column in group_columns:
        if column in df.columns:
            group_reports[column] = group_summary(column)
    report["groups"] = group_reports
    return report


def null_shuffle_strategy_test(
    predictions: str | Path | pd.DataFrame,
    *,
    horizon: int = 1,
    n_iter: int = 500,
    seed: int = 42,
    probability_column: str = "predicted_positive_probability",
    return_column: str | None = None,
    long_threshold: float = 0.60,
    short_threshold: float | None = None,
    long_threshold_column: str | None = None,
    short_threshold_column: str | None = None,
    allow_short: bool = False,
    cost_bps: float = 0.0,
    slippage_bps: float = 0.0,
    out_path: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Shuffle realized event returns to test whether strategy results survive a simple null."""
    df = pd.read_csv(predictions) if not isinstance(predictions, pd.DataFrame) else predictions.copy()
    if return_column is None:
        return_column = f"car_market_model_h{horizon}"
    _, actual = simulate_event_strategy(
        df,
        horizon=horizon,
        probability_column=probability_column,
        return_column=return_column,
        long_threshold=long_threshold,
        short_threshold=short_threshold,
        long_threshold_column=long_threshold_column,
        short_threshold_column=short_threshold_column,
        allow_short=allow_short,
        cost_bps=cost_bps,
        slippage_bps=slippage_bps,
    )
    rng = np.random.default_rng(seed)
    clean = df.copy()
    if return_column not in clean.columns:
        raise ValueError(f"Missing return column {return_column}")
    returns = clean[return_column].to_numpy(copy=True)
    rows = []
    for i in range(int(n_iter)):
        shuffled = clean.copy()
        shuffled[return_column] = rng.permutation(returns)
        _, report = simulate_event_strategy(
            shuffled,
            horizon=horizon,
            probability_column=probability_column,
            return_column=return_column,
            long_threshold=long_threshold,
            short_threshold=short_threshold,
            long_threshold_column=long_threshold_column,
            short_threshold_column=short_threshold_column,
            allow_short=allow_short,
            cost_bps=cost_bps,
            slippage_bps=slippage_bps,
        )
        rows.append(
            {
                "iteration": i,
                "n_trades": report.get("n_trades", 0),
                "mean_net_event_return": report.get("mean_net_event_return", np.nan),
                "cumulative_net_return": report.get("cumulative_net_return", np.nan),
                "hit_rate": report.get("hit_rate", np.nan),
            }
        )
    placebo = pd.DataFrame(rows)
    metric = "mean_net_event_return"
    actual_metric = actual.get(metric, np.nan)
    dist = pd.to_numeric(placebo[metric], errors="coerce").dropna()
    if len(dist) and actual_metric is not None and not pd.isna(actual_metric):
        p_value = float(((dist >= float(actual_metric)).sum() + 1) / (len(dist) + 1))
        z = float((float(actual_metric) - dist.mean()) / dist.std(ddof=1)) if len(dist) > 1 and dist.std(ddof=1) > 0 else None
    else:
        p_value = None
        z = None
    report = {
        "n_iter": int(n_iter),
        "seed": int(seed),
        "actual_strategy_report": actual,
        "null_metric": metric,
        "actual_metric": float(actual_metric) if actual_metric is not None and not pd.isna(actual_metric) else None,
        "null_mean": float(dist.mean()) if len(dist) else None,
        "null_std": float(dist.std(ddof=1)) if len(dist) > 1 else None,
        "one_sided_p_value_actual_ge_null": p_value,
        "z_score_vs_null": z,
    }
    if out_path:
        p = ensure_parent(out_path)
        placebo.to_csv(p, index=False)
        report["null_distribution_path"] = str(p)
    return placebo, report


def purged_walk_forward_direction_model(
    event_study_path: str | Path,
    *,
    horizon: int = 1,
    min_train: int = 40,
    purge_days: int | None = None,
    out_predictions: str | Path | None = None,
    out_report: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Expanding walk-forward classifier that purges overlapping recent rows.

    If purge_days is not supplied, it defaults to the forecast horizon.  This is
    intentionally conservative: it removes training rows whose reaction windows
    could overlap with the test row.
    """
    purge_days = int(horizon if purge_days is None else purge_days)
    df = load_event_study(event_study_path)
    frame, y = modeling_frame(df, horizon=horizon)
    date_col = "reaction_start" if "reaction_start" in frame.columns else "event_time"
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    order = frame[date_col].sort_values(kind="mergesort").index
    frame = frame.loc[order].reset_index(drop=True)
    y = y.loc[order].reset_index(drop=True)
    min_train = max(2, int(min_train))
    if len(frame) <= min_train:
        raise ValueError(f"Need more than min_train={min_train} usable events for walk-forward validation")
    rows: list[dict[str, object]] = []
    for i in range(min_train, len(frame)):
        test_date = pd.Timestamp(frame.iloc[i][date_col])
        cutoff = test_date - pd.Timedelta(days=purge_days)
        train_mask = frame.iloc[:i][date_col] < cutoff
        X_train = frame.iloc[:i].loc[train_mask].copy()
        y_train = y.iloc[:i].loc[train_mask].copy()
        X_one = frame.iloc[[i]].copy()
        if len(X_train) < min_train:
            status = "skipped_not_enough_purged_train"
            proba = np.nan
            pred = np.nan
            base_rate = float(y.iloc[:i].mean())
        else:
            base_rate = float(np.clip(y_train.mean(), 1e-6, 1.0 - 1e-6))
            if y_train.nunique() < 2:
                status = "fallback_base_rate_one_class_train"
                proba = base_rate
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
                "event_subtype": row.get("event_subtype", ""),
                "event_family": row.get("event_family", ""),
                "y_true": int(y.iloc[i]),
                "actual_positive": int(y.iloc[i]),
                "predicted_positive_probability": proba,
                "predicted_positive": pred,
                "baseline_positive_probability": base_rate,
                "model_status": status,
                "purge_days": purge_days,
                "train_rows_after_purge": int(len(X_train)),
                f"car_market_model_h{horizon}": row.get(f"car_market_model_h{horizon}", np.nan),
                f"car_market_model_simple_h{horizon}": row.get(f"car_market_model_simple_h{horizon}", np.nan),
                f"raw_return_h{horizon}": row.get(f"raw_return_h{horizon}", np.nan),
            }
        )
    pred_df = pd.DataFrame(rows)
    eval_df = pred_df[pred_df["predicted_positive_probability"].notna()].copy()
    report: dict[str, object] = {
        "horizon": int(horizon),
        "min_train": int(min_train),
        "purge_days": int(purge_days),
        "n_events": int(len(frame)),
        "n_predictions": int(len(eval_df)),
        "n_skipped": int(len(pred_df) - len(eval_df)),
        "categorical_features": available_features(frame)[0],
        "numeric_features": available_features(frame)[1],
        "warnings": ["Purged walk-forward metrics are diagnostics only; test placebo controls and costs before trusting them."],
    }
    if not eval_df.empty:
        from sklearn.metrics import accuracy_score, balanced_accuracy_score, brier_score_loss, log_loss, roc_auc_score

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
    if out_report:
        p = ensure_parent(out_report)
        p.write_text(json.dumps(report, indent=2, default=str))
        report["report_path"] = str(p)
    return pred_df, report


def run_research_backtest(
    event_study_path: str | Path,
    out_dir: str | Path,
    *,
    horizon: int = 1,
    min_train: int = 40,
    purge_days: int | None = None,
    probability_threshold: float = 0.60,
    threshold_mode: str = "fixed",
    candidate_thresholds: Iterable[float] | None = None,
    min_threshold_selection_rows: int = 30,
    allow_short: bool = False,
    cost_bps: float = 0.0,
    slippage_bps: float = 0.0,
    calibration_bins: int = 10,
    null_iterations: int = 500,
    seed: int = 42,
) -> dict[str, object]:
    out = ensure_dir(out_dir)
    pred_path = out / "walk_forward_predictions.csv"
    walk_report_path = out / "walk_forward_report.json"
    cal_path = out / "calibration.csv"
    trades_path = out / "strategy_trades.csv"
    null_path = out / "null_shuffle_distribution.csv"
    pred_df, walk_report = purged_walk_forward_direction_model(
        event_study_path,
        horizon=horizon,
        min_train=min_train,
        purge_days=purge_days,
        out_predictions=pred_path,
        out_report=walk_report_path,
    )
    usable = pred_df[pred_df["predicted_positive_probability"].notna()].copy()
    threshold_mode = str(threshold_mode).lower().strip()
    if threshold_mode not in {"fixed", "nested_expanding"}:
        raise ValueError("threshold_mode must be fixed or nested_expanding")
    threshold_report: dict[str, object]
    strategy_input = usable
    long_threshold_column: str | None = None
    short_threshold_column: str | None = None
    if threshold_mode == "nested_expanding":
        strategy_input, threshold_report = apply_nested_expanding_thresholds(
            usable,
            candidate_thresholds=candidate_thresholds or [probability_threshold],
            default_threshold=probability_threshold,
            min_threshold_selection_rows=min_threshold_selection_rows,
            horizon=horizon,
            allow_short=allow_short,
            cost_bps=cost_bps,
            slippage_bps=slippage_bps,
        )
        long_threshold_column = "selected_long_threshold"
        short_threshold_column = "selected_short_threshold"
    else:
        threshold_report = {
            "threshold_mode": "fixed",
            "candidate_thresholds": [],
            "default_threshold": float(probability_threshold),
            "rows_using_default_threshold": int(len(usable)),
            "selected_threshold_summary": {str(float(probability_threshold)): int(len(usable))},
            "selection_status_counts": {"fixed": int(len(usable))},
        }
    cal, cal_report = calibration_table(usable, bins=calibration_bins, out_path=cal_path)
    trades, strategy_report = simulate_event_strategy(
        strategy_input,
        horizon=horizon,
        long_threshold=probability_threshold,
        long_threshold_column=long_threshold_column,
        short_threshold_column=short_threshold_column,
        allow_short=allow_short,
        cost_bps=cost_bps,
        slippage_bps=slippage_bps,
        out_trades=trades_path,
    )
    strategy_report["threshold_mode"] = threshold_mode
    concentration_report = concentration_diagnostics(trades)
    _, null_report = null_shuffle_strategy_test(
        strategy_input,
        horizon=horizon,
        n_iter=null_iterations,
        seed=seed,
        long_threshold=probability_threshold,
        long_threshold_column=long_threshold_column,
        short_threshold_column=short_threshold_column,
        allow_short=allow_short,
        cost_bps=cost_bps,
        slippage_bps=slippage_bps,
        out_path=null_path,
    )
    report = {
        "event_study_path": str(event_study_path),
        "out_dir": str(out),
        "horizon": int(horizon),
        "walk_forward": walk_report,
        "calibration": cal_report,
        "threshold_selection": threshold_report,
        "strategy": strategy_report,
        "concentration": concentration_report,
        "null_shuffle": null_report,
        "artifacts": {
            "predictions": str(pred_path),
            "walk_forward_report": str(walk_report_path),
            "calibration": str(cal_path),
            "trades": str(trades_path),
            "null_distribution": str(null_path),
        },
        "warnings": [
            "This is a research falsification harness, not a trading system.",
            "Positive results must survive fresh data, data-vendor changes, placebo dates, peer controls, and realistic execution assumptions.",
        ],
    }
    report_path = out / "research_backtest_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))
    report["artifacts"]["report"] = str(report_path)
    return report


def _choose_random_trading_dates(index: pd.DatetimeIndex, blocked: set[pd.Timestamp], n: int, rng: np.random.Generator) -> list[pd.Timestamp]:
    choices = [pd.Timestamp(d).normalize() for d in index if pd.Timestamp(d).normalize() not in blocked]
    if not choices:
        return []
    take = rng.choice(len(choices), size=int(n), replace=len(choices) < int(n))
    return [choices[int(i)] for i in take]


def make_placebo_events(
    events_path: str | Path,
    prices_dir: str | Path,
    out_path: str | Path,
    *,
    n_per_event: int = 1,
    mode: str = "random",
    shift_days: Iterable[int] = (30, 60, 90, -30, -60, -90),
    avoid_window_days: int = 10,
    seed: int = 42,
) -> tuple[pd.DataFrame, BacktestDiagnostics]:
    """Create non-event placebo controls that preserve ticker/session metadata."""
    events = load_events(events_path)
    rng = np.random.default_rng(seed)
    diag = BacktestDiagnostics(rows_total=len(events))
    rows: list[dict[str, object]] = []
    mode = str(mode).lower().strip()
    shifts = [int(v) for v in shift_days]
    for _, event in events.iterrows():
        ticker = str(event["ticker"]).upper()
        try:
            price_df = load_price_csv(prices_dir, ticker)
        except FileNotFoundError:
            diag.add_skip(f"missing_price_{ticker}")
            continue
        index = pd.DatetimeIndex(price_df["date"]).normalize()
        event_date = pd.Timestamp(event["event_time"]).normalize()
        blocked: set[pd.Timestamp] = set()
        ticker_events = events[events["ticker"].astype(str).str.upper() == ticker]
        for d in pd.to_datetime(ticker_events["event_time"], errors="coerce").dropna():
            for offset in range(-int(avoid_window_days), int(avoid_window_days) + 1):
                blocked.add((pd.Timestamp(d).normalize() + pd.Timedelta(days=offset)).normalize())
        if mode == "random":
            dates = _choose_random_trading_dates(index, blocked, n_per_event, rng)
        elif mode == "shift":
            dates = []
            for j in range(int(n_per_event)):
                shifted = event_date + pd.Timedelta(days=shifts[j % len(shifts)])
                pos = index.searchsorted(shifted, side="left")
                if pos < len(index):
                    candidate = pd.Timestamp(index[pos]).normalize()
                    if candidate not in blocked:
                        dates.append(candidate)
        else:
            raise ValueError("mode must be 'random' or 'shift'")
        if not dates:
            diag.add_skip(f"no_placebo_date_{ticker}")
            continue
        for j, d in enumerate(dates, start=1):
            row = event.to_dict()
            row["original_event_id"] = event["event_id"]
            row["event_id"] = f"{event['event_id']}__placebo{j:02d}"
            original_time = pd.Timestamp(event["event_time"])
            placebo_time = pd.Timestamp(d) + pd.Timedelta(hours=original_time.hour, minutes=original_time.minute, seconds=original_time.second)
            row["event_time"] = placebo_time.isoformat()
            row["event_type"] = "placebo"
            row["event_subtype"] = "non_event_control"
            row["event_family"] = "placebo_control"
            row["summary"] = f"Placebo non-event control for {event['event_id']}"
            row["source_type"] = "placebo"
            row["source_url"] = ""
            row["expectedness"] = "unknown"
            row["surprise_direction"] = "unknown"
            row["surprise_magnitude"] = "unknown"
            row["materiality"] = 0.0
            rows.append(row)
        diag.rows_used += len(dates)
    out = pd.DataFrame(rows)
    p = ensure_parent(out_path)
    out.to_csv(p, index=False)
    return out, diag


def _load_peer_map(peer_map: str | Path | None, universe: str | Path | None, events: pd.DataFrame) -> dict[str, str]:
    if peer_map:
        df = pd.read_csv(peer_map)
        if not {"ticker", "peer_ticker"}.issubset(df.columns):
            raise ValueError("peer-map CSV must include ticker and peer_ticker columns")
        return {str(r.ticker).upper(): str(r.peer_ticker).upper() for r in df.itertuples(index=False)}
    if universe:
        df = pd.read_csv(universe)
        if "ticker" not in df.columns:
            raise ValueError("universe CSV must include ticker column")
        tickers = sorted(df["ticker"].dropna().astype(str).str.upper().unique())
    else:
        tickers = sorted(events["ticker"].dropna().astype(str).str.upper().unique())
    if len(tickers) < 2:
        raise ValueError("Need at least two tickers to construct peer controls")
    return {ticker: tickers[(i + 1) % len(tickers)] for i, ticker in enumerate(tickers)}


def make_peer_control_events(
    events_path: str | Path,
    out_path: str | Path,
    *,
    peer_map: str | Path | None = None,
    universe: str | Path | None = None,
) -> tuple[pd.DataFrame, BacktestDiagnostics]:
    """Create peer controls by replacing the affected ticker with a peer ticker."""
    events = load_events(events_path)
    mapping = _load_peer_map(peer_map, universe, events)
    diag = BacktestDiagnostics(rows_total=len(events))
    rows: list[dict[str, object]] = []
    for _, event in events.iterrows():
        ticker = str(event["ticker"]).upper()
        peer = mapping.get(ticker)
        if not peer or peer == ticker:
            diag.add_skip(f"missing_peer_{ticker}")
            continue
        row = event.to_dict()
        row["original_event_id"] = event["event_id"]
        row["original_ticker"] = ticker
        row["event_id"] = f"{event['event_id']}__peer_{peer}"
        row["ticker"] = peer
        row["event_type"] = "peer_control"
        row["event_subtype"] = f"peer_{event.get('event_type', 'event')}"
        row["event_family"] = "peer_control"
        row["summary"] = f"Peer-control event for {event['event_id']}: original ticker {ticker}, peer ticker {peer}."
        row["source_type"] = "peer_control"
        row["source_url"] = ""
        rows.append(row)
        diag.rows_used += 1
    out = pd.DataFrame(rows)
    p = ensure_parent(out_path)
    out.to_csv(p, index=False)
    return out, diag
