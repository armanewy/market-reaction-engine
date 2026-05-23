from __future__ import annotations

from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd

from .modeling import load_event_study
from .paths import ensure_parent


def _stderr(series: pd.Series) -> float:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) <= 1:
        return float("nan")
    return float(s.std(ddof=1) / sqrt(len(s)))


def base_rate_table(
    event_study_path: str | Path,
    *,
    horizon: int = 1,
    group_by: str = "event_subtype,surprise_direction,surprise_magnitude",
    min_count: int = 3,
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    """Summarize base-rate abnormal reactions by event metadata bins."""
    df = load_event_study(event_study_path)
    car = f"car_market_model_h{horizon}"
    simple = f"car_market_model_simple_h{horizon}"
    direction = f"target_direction_h{horizon}"
    significant = f"significant_95_h{horizon}"
    zcol = f"z_h{horizon}"
    needed = ["event_status", car]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required event-study columns: {missing}")
    frame = df[(df["event_status"] == "ok") & df[car].notna()].copy()
    groups = [g.strip() for g in group_by.split(",") if g.strip()]
    if not groups:
        groups = ["event_type"]
    for g in groups:
        if g not in frame.columns:
            frame[g] = "missing"
        frame[g] = frame[g].fillna("unknown").astype(str).str.lower()

    frame["_positive"] = pd.to_numeric(frame[car], errors="coerce") > 0
    if significant in frame.columns:
        frame["_significant"] = frame[significant].astype(str).str.lower().isin(["true", "1", "yes"])
    else:
        frame["_significant"] = False
    if simple not in frame.columns:
        frame[simple] = np.exp(pd.to_numeric(frame[car], errors="coerce")) - 1.0

    agg = (
        frame.groupby(groups, dropna=False)
        .agg(
            n=(car, "count"),
            positive_rate=("_positive", "mean"),
            significant_rate=("_significant", "mean"),
            mean_car=(car, "mean"),
            median_car=(car, "median"),
            std_car=(car, "std"),
            stderr_car=(car, _stderr),
            mean_simple_car=(simple, "mean"),
            median_simple_car=(simple, "median"),
            mean_z=(zcol, "mean") if zcol in frame.columns else (car, "mean"),
        )
        .reset_index()
    )
    agg["t_stat_mean_car"] = agg["mean_car"] / agg["stderr_car"].replace(0, np.nan)
    agg = agg[agg["n"] >= int(min_count)].copy()
    agg = agg.sort_values(["n", "mean_car"], ascending=[False, False]).reset_index(drop=True)
    if out_path:
        p = ensure_parent(out_path)
        agg.to_csv(p, index=False)
    return agg
