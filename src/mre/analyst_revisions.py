from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .events import load_events
from .paths import ensure_parent
from .release_times import normalize_timestamp

REVISION_COLUMNS = [
    "event_id",
    "ticker",
    "estimate_time",
    "analyst_id",
    "metric",
    "fiscal_period",
    "estimate_value",
    "estimate_source_type",
    "estimate_source_url",
    "estimate_notes",
]

REVISION_ALIASES = {
    "asof_time": "estimate_time",
    "timestamp": "estimate_time",
    "broker": "analyst_id",
    "analyst": "analyst_id",
    "field": "metric",
    "value": "estimate_value",
    "estimate": "estimate_value",
    "source": "estimate_source_type",
    "source_url": "estimate_source_url",
}

METRIC_TO_CONSENSUS_COLUMN = {
    "eps": "consensus_eps",
    "revenue": "consensus_revenue",
    "gross_margin": "consensus_gross_margin",
    "forward_revenue": "consensus_forward_revenue",
    "forward_eps": "consensus_forward_eps",
    "forward_gross_margin": "consensus_forward_gross_margin",
}


@dataclass
class AnalystRevisionDiagnostics:
    events_total: int = 0
    events_with_revision_features: int = 0
    events_skipped: int = 0
    skipped_reasons: dict[str, int] | None = None

    def __post_init__(self) -> None:
        if self.skipped_reasons is None:
            self.skipped_reasons = {}

    def add_skip(self, reason: str) -> None:
        self.events_skipped += 1
        assert self.skipped_reasons is not None
        self.skipped_reasons[reason] = self.skipped_reasons.get(reason, 0) + 1

    def to_dict(self) -> dict:
        return {
            "events_total": self.events_total,
            "events_with_revision_features": self.events_with_revision_features,
            "events_skipped": self.events_skipped,
            "skipped_reasons": self.skipped_reasons or {},
        }


def _normalize_alias_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.loc[:, ~pd.Index(df.columns).duplicated()].copy()
    for src, dst in REVISION_ALIASES.items():
        if src in out.columns and dst not in out.columns:
            out[dst] = out[src]
    return out


def _sanitize_metric(value: object) -> str:
    text = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "estimated_eps": "eps",
        "consensus_eps": "eps",
        "earnings_per_share": "eps",
        "sales": "revenue",
        "rev": "revenue",
        "consensus_revenue": "revenue",
        "grossmargin": "gross_margin",
        "gross_margin_pct": "gross_margin",
        "forward_sales": "forward_revenue",
        "guidance_revenue": "forward_revenue",
        "forward_gross_margin_pct": "forward_gross_margin",
    }
    return aliases.get(text, text)


def make_analyst_revisions_template(events_path: str | Path, out_path: str | Path) -> pd.DataFrame:
    events = load_events(events_path)
    rows = []
    for _, event in events.iterrows():
        for metric in ["eps", "revenue", "gross_margin", "forward_revenue"]:
            rows.append(
                {
                    "event_id": event["event_id"],
                    "ticker": event["ticker"],
                    "estimate_time": "",
                    "analyst_id": "",
                    "metric": metric,
                    "fiscal_period": "",
                    "estimate_value": "",
                    "estimate_source_type": "manual_or_vendor",
                    "estimate_source_url": "",
                    "estimate_notes": "Use point-in-time estimate revisions known before event_time.",
                }
            )
    df = pd.DataFrame(rows, columns=REVISION_COLUMNS)
    p = ensure_parent(out_path)
    df.to_csv(p, index=False)
    return df


def load_analyst_revisions(path: str | Path) -> pd.DataFrame:
    df = _normalize_alias_columns(pd.read_csv(path))
    required = ["ticker", "estimate_time", "metric", "estimate_value"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Analyst revision file is missing required columns: {missing}")
    if "analyst_id" not in df.columns:
        df["analyst_id"] = "unknown"
    if "event_id" not in df.columns:
        df["event_id"] = ""
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["event_id"] = df["event_id"].fillna("").astype(str)
    df["estimate_time"] = df["estimate_time"].map(normalize_timestamp)
    df["metric"] = df["metric"].map(_sanitize_metric)
    df["estimate_value"] = pd.to_numeric(df["estimate_value"], errors="coerce")
    df["analyst_id"] = df["analyst_id"].fillna("unknown").astype(str)
    df = df.dropna(subset=["estimate_time", "estimate_value"])
    if df.empty:
        raise ValueError("No usable analyst revision rows after parsing")
    return df.sort_values(["ticker", "metric", "analyst_id", "estimate_time"]).reset_index(drop=True)


def _latest_per_analyst(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return rows
    return rows.sort_values("estimate_time").groupby(["metric", "analyst_id"], as_index=False).tail(1)


def _metric_features(metric: str, current: pd.DataFrame, previous: pd.DataFrame, window: int) -> dict[str, float]:
    cur = current[current["metric"] == metric]
    prev = previous[previous["metric"] == metric]
    features: dict[str, float] = {}
    prefix = f"analyst_{metric}"
    if cur.empty:
        features[f"{prefix}_count"] = np.nan
        features[f"{prefix}_consensus"] = np.nan
        features[f"{prefix}_dispersion"] = np.nan
        features[f"{prefix}_revision_count_{window}d"] = 0.0
        features[f"{prefix}_revision_mean_{window}d"] = np.nan
        features[f"{prefix}_revision_median_{window}d"] = np.nan
        features[f"{prefix}_revision_pct_up_{window}d"] = np.nan
        features[f"{prefix}_revision_pct_down_{window}d"] = np.nan
        return features
    features[f"{prefix}_count"] = float(cur["analyst_id"].nunique())
    features[f"{prefix}_consensus"] = float(cur["estimate_value"].mean())
    features[f"{prefix}_dispersion"] = float(cur["estimate_value"].std(ddof=1)) if len(cur) > 1 else 0.0
    if prev.empty:
        features[f"{prefix}_revision_count_{window}d"] = 0.0
        features[f"{prefix}_revision_mean_{window}d"] = np.nan
        features[f"{prefix}_revision_median_{window}d"] = np.nan
        features[f"{prefix}_revision_pct_up_{window}d"] = np.nan
        features[f"{prefix}_revision_pct_down_{window}d"] = np.nan
        return features
    joined = cur[["analyst_id", "estimate_value"]].merge(
        prev[["analyst_id", "estimate_value"]],
        on="analyst_id",
        how="inner",
        suffixes=("_current", "_previous"),
    )
    if joined.empty:
        features[f"{prefix}_revision_count_{window}d"] = 0.0
        features[f"{prefix}_revision_mean_{window}d"] = np.nan
        features[f"{prefix}_revision_median_{window}d"] = np.nan
        features[f"{prefix}_revision_pct_up_{window}d"] = np.nan
        features[f"{prefix}_revision_pct_down_{window}d"] = np.nan
        return features
    delta = joined["estimate_value_current"] - joined["estimate_value_previous"]
    changed = delta[delta.abs() > 1e-12]
    features[f"{prefix}_revision_count_{window}d"] = float(len(changed))
    features[f"{prefix}_revision_mean_{window}d"] = float(delta.mean())
    features[f"{prefix}_revision_median_{window}d"] = float(delta.median())
    features[f"{prefix}_revision_pct_up_{window}d"] = float((delta > 0).mean())
    features[f"{prefix}_revision_pct_down_{window}d"] = float((delta < 0).mean())
    return features


def compute_analyst_revision_features(
    events_path: str | Path,
    revisions_path: str | Path,
    *,
    windows: Iterable[int] = (7, 30),
    metrics: Iterable[str] = ("eps", "revenue", "gross_margin", "forward_revenue"),
    max_history_days: int | None = 370,
) -> tuple[pd.DataFrame, AnalystRevisionDiagnostics]:
    events = load_events(events_path)
    revisions = load_analyst_revisions(revisions_path)
    metrics = tuple(_sanitize_metric(m) for m in metrics)
    windows = tuple(int(w) for w in windows)
    diag = AnalystRevisionDiagnostics(events_total=len(events))
    rows: list[dict[str, object]] = []

    for _, event in events.iterrows():
        event_time = normalize_timestamp(event["event_time"])
        ticker = str(event["ticker"]).upper()
        candidates = revisions[revisions["ticker"] == ticker].copy()
        if "event_id" in candidates.columns:
            exact = candidates[candidates["event_id"].astype(str) == str(event["event_id"])]
            if not exact.empty:
                candidates = exact.copy()
        candidates = candidates[candidates["estimate_time"] <= event_time]
        if max_history_days is not None:
            candidates = candidates[candidates["estimate_time"] >= event_time - pd.Timedelta(days=max_history_days)]
        row: dict[str, object] = {"event_id": event["event_id"], "ticker": ticker}
        if candidates.empty:
            row["analyst_revision_status"] = "skipped"
            row["analyst_revision_reason"] = "no pre-event estimates"
            diag.add_skip("no pre-event estimates")
            rows.append(row)
            continue
        current = _latest_per_analyst(candidates[candidates["metric"].isin(metrics)])
        if current.empty:
            row["analyst_revision_status"] = "skipped"
            row["analyst_revision_reason"] = "no requested metric estimates"
            diag.add_skip("no requested metric estimates")
            rows.append(row)
            continue
        row["analyst_revision_status"] = "ok"
        row["analyst_revision_reason"] = ""
        diag.events_with_revision_features += 1
        for metric in metrics:
            cur_metric = current[current["metric"] == metric]
            if not cur_metric.empty:
                col = METRIC_TO_CONSENSUS_COLUMN.get(metric)
                if col:
                    row[col] = float(cur_metric["estimate_value"].mean())
                row[f"analyst_{metric}_count"] = float(cur_metric["analyst_id"].nunique())
                row[f"analyst_{metric}_consensus"] = float(cur_metric["estimate_value"].mean())
                row[f"analyst_{metric}_dispersion"] = float(cur_metric["estimate_value"].std(ddof=1)) if len(cur_metric) > 1 else 0.0
        for window in windows:
            cutoff = event_time - pd.Timedelta(days=window)
            previous = _latest_per_analyst(candidates[candidates["estimate_time"] <= cutoff])
            for metric in metrics:
                row.update(_metric_features(metric, current, previous, window))
        rows.append(row)
    return pd.DataFrame(rows), diag


def merge_analyst_revisions(
    events_path: str | Path,
    revisions_path: str | Path,
    out_path: str | Path,
    *,
    windows: Iterable[int] = (7, 30),
    metrics: Iterable[str] = ("eps", "revenue", "gross_margin", "forward_revenue"),
) -> tuple[pd.DataFrame, AnalystRevisionDiagnostics]:
    events = load_events(events_path)
    features, diag = compute_analyst_revision_features(events_path, revisions_path, windows=windows, metrics=metrics)
    merged = events.merge(features, on=["event_id", "ticker"], how="left", suffixes=("", "_analyst"))
    # Fill consensus columns only if the event file did not already contain a curated value.
    for metric, col in METRIC_TO_CONSENSUS_COLUMN.items():
        suff = f"{col}_analyst"
        if suff in merged.columns:
            if col in merged.columns:
                existing = pd.to_numeric(merged[col], errors="coerce")
                merged[col] = existing.where(existing.notna(), merged[suff])
            else:
                merged[col] = merged[suff]
            merged = merged.drop(columns=[suff])
    p = ensure_parent(out_path)
    merged.to_csv(p, index=False)
    return merged, diag
