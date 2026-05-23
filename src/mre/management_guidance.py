from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .paths import ensure_parent


READY_STATUS = "ready_for_model"


@dataclass
class BridgeDiagnostics:
    rows_total: int = 0
    events_with_actual_revenue: int = 0
    events_with_current_guidance_revenue_mid: int = 0
    events_with_prior_guidance_candidate: int = 0
    ready_for_model: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    ready_by_ticker: dict[str, int] = field(default_factory=dict)
    tickers_with_zero_ready_rows: list[str] = field(default_factory=list)
    median_prior_event_gap_days: float | None = None
    date_range: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def _text_value(row: pd.Series, col: str, default: str = "") -> str:
    value = row.get(col, default)
    if pd.isna(value):
        return default
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def _direction(pct: float) -> str:
    if pd.isna(pct):
        return "unknown"
    if pct <= -0.02:
        return "negative"
    if pct >= 0.02:
        return "positive"
    return "neutral"


def _magnitude(pct: float) -> str:
    if pd.isna(pct):
        return "unknown"
    value = abs(float(pct))
    if value >= 0.10:
        return "high"
    if value >= 0.04:
        return "medium"
    if value >= 0.02:
        return "low"
    return "neutral"


def _merge_metadata(features: pd.DataFrame, events_path: str | Path | None) -> pd.DataFrame:
    out = features.copy()
    if not events_path:
        return out
    events = pd.read_csv(events_path)
    keep = [
        c
        for c in [
            "event_id",
            "release_session",
            "source_type",
            "source_url",
            "summary",
            "event_type",
            "event_subtype",
            "event_family",
            "sector_benchmark",
            "materiality",
            "review_status",
            "label_quality",
            "evidence_status",
        ]
        if c in events.columns
    ]
    if "event_id" not in keep:
        return out
    events = events[keep].drop_duplicates("event_id")
    merged = out.merge(events, on="event_id", how="left", suffixes=("", "_event"))
    for col in [c for c in keep if c != "event_id"]:
        suff = f"{col}_event"
        if suff in merged.columns:
            if col in merged.columns:
                base = merged[col].astype(str).str.strip()
                missing = merged[col].isna() | base.eq("") | base.str.lower().isin(["nan", "none", "null"])
                merged.loc[missing, col] = merged.loc[missing, suff]
                merged = merged.drop(columns=[suff])
            else:
                merged = merged.rename(columns={suff: col})
    return merged


def build_management_guidance_bridge(
    features_path: str | Path,
    out_path: str | Path,
    *,
    events_path: str | Path | None = None,
    failures_path: str | Path | None = None,
    min_confidence: float = 0.80,
    min_prior_event_gap_days: int = 45,
    max_prior_event_gap_days: int = 190,
    min_actual_to_prior_ratio: float = 0.50,
    max_actual_to_prior_ratio: float = 1.75,
) -> tuple[pd.DataFrame, BridgeDiagnostics]:
    """Build a source-grounded management-guidance surprise bridge.

    The bridge compares current actual revenue against the immediately prior
    earnings event's next-quarter revenue guidance midpoint for the same ticker.
    It deliberately rejects rows with missing actuals, missing prior guidance,
    low parser confidence, or implausible actual/prior ratios that usually
    indicate annual/period extraction mistakes.
    """
    features = pd.read_csv(features_path)
    features = _merge_metadata(features, events_path)
    if "event_id" not in features.columns or "ticker" not in features.columns or "event_time" not in features.columns:
        raise ValueError("features_path must include event_id, ticker, and event_time")

    out = features.copy()
    out["event_time"] = pd.to_datetime(out["event_time"], errors="coerce")
    for col in [
        "actual_revenue",
        "guidance_revenue_mid",
        "guidance_revenue_low",
        "guidance_revenue_high",
        "actual_revenue_confidence",
        "guidance_revenue_mid_confidence",
        "guidance_revenue_low_confidence",
        "guidance_revenue_high_confidence",
        "actual_gross_margin",
        "actual_gross_margin_confidence",
        "guidance_gross_margin_mid",
        "guidance_gross_margin_mid_confidence",
    ]:
        out[col] = _num(out, col)

    rows: list[dict] = []
    for ticker, group in out.sort_values(["ticker", "event_time", "event_id"]).groupby("ticker", sort=True):
        prior: pd.Series | None = None
        for _, event in group.iterrows():
            actual = event.get("actual_revenue", np.nan)
            current_guidance = event.get("guidance_revenue_mid", np.nan)
            prior_guidance = np.nan if prior is None else prior.get("guidance_revenue_mid", np.nan)
            actual_conf = event.get("actual_revenue_confidence", np.nan)
            current_guidance_conf = event.get("guidance_revenue_mid_confidence", np.nan)
            prior_guidance_conf = np.nan if prior is None else prior.get("guidance_revenue_mid_confidence", np.nan)
            event_time = event.get("event_time")
            prior_event_time = None if prior is None else prior.get("event_time")
            gap_days = np.nan
            if prior is not None and not pd.isna(event_time) and not pd.isna(prior_event_time):
                gap_days = (pd.Timestamp(event_time) - pd.Timestamp(prior_event_time)).total_seconds() / 86400
            flags: list[str] = []

            if pd.isna(event_time):
                status = "bad_timestamp"
            elif prior is not None and pd.isna(prior_event_time):
                status = "bad_timestamp"
            elif pd.isna(actual):
                status = "missing_actual_revenue"
            elif prior is None or pd.isna(prior_guidance):
                status = "missing_prior_guidance"
            elif pd.isna(actual_conf) or float(actual_conf) < min_confidence:
                status = "low_actual_revenue_confidence"
            elif pd.isna(prior_guidance_conf) or float(prior_guidance_conf) < min_confidence:
                status = "low_prior_guidance_confidence"
            elif pd.isna(gap_days):
                status = "bad_timestamp"
            elif gap_days <= 0:
                status = "duplicate_or_same_day_event"
            elif gap_days < min_prior_event_gap_days:
                status = "prior_event_gap_too_short"
            elif gap_days > max_prior_event_gap_days:
                status = "prior_event_gap_too_long"
            else:
                ratio = float(actual) / abs(float(prior_guidance)) if prior_guidance else np.nan
                if pd.isna(ratio) or ratio < min_actual_to_prior_ratio or ratio > max_actual_to_prior_ratio:
                    status = "ambiguous"
                    flags.append("actual_to_prior_guidance_ratio_out_of_bounds")
                else:
                    status = READY_STATUS

            if pd.isna(current_guidance):
                flags.append("missing_current_guidance")
            elif not pd.isna(current_guidance_conf) and float(current_guidance_conf) < min_confidence:
                flags.append("low_current_guidance_confidence")

            surprise = np.nan
            surprise_pct = np.nan
            if not pd.isna(actual) and not pd.isna(prior_guidance) and prior_guidance:
                surprise = float(actual) - float(prior_guidance)
                surprise_pct = surprise / abs(float(prior_guidance))

            new_guidance_vs_actual = np.nan
            new_guidance_vs_actual_pct = np.nan
            if not pd.isna(current_guidance) and not pd.isna(actual) and actual:
                new_guidance_vs_actual = float(current_guidance) - float(actual)
                new_guidance_vs_actual_pct = new_guidance_vs_actual / abs(float(actual))

            confidence_values = [actual_conf, prior_guidance_conf]
            if not pd.isna(current_guidance_conf):
                confidence_values.append(current_guidance_conf)
            confidence_values = [float(v) for v in confidence_values if not pd.isna(v)]
            parser_confidence_min = min(confidence_values) if confidence_values else np.nan

            row = {
                "event_id": event["event_id"],
                "ticker": str(ticker).upper(),
                "event_time": event_time.isoformat() if not pd.isna(event_time) else "",
                "release_session": _text_value(event, "release_session", "unknown"),
                "event_type": _text_value(event, "event_type", "earnings"),
                "event_subtype": "management_guidance_bridge",
                "event_family": _text_value(event, "event_family", "earnings_guidance"),
                "summary": _text_value(event, "summary", f"{ticker} management-guidance bridge event."),
                "source_type": _text_value(event, "source_type", "sec_exhibit99_management_guidance"),
                "source_url": _text_value(event, "source_url"),
                "sector_benchmark": _text_value(event, "sector_benchmark", "SMH"),
                "materiality": event.get("materiality", 0.7) if not pd.isna(event.get("materiality", np.nan)) else 0.7,
                "review_status": "reviewed",
                "label_quality": "management_guidance_bridge",
                "evidence_status": "source_backed",
                "source_doc_ids": _text_value(event, "source_doc_ids"),
                "actual_revenue": actual,
                "actual_revenue_confidence": actual_conf,
                "actual_revenue_evidence": _text_value(event, "actual_revenue_evidence"),
                "current_guidance_revenue_mid": current_guidance,
                "current_guidance_revenue_low": event.get("guidance_revenue_low", np.nan),
                "current_guidance_revenue_high": event.get("guidance_revenue_high", np.nan),
                "current_guidance_revenue_confidence": current_guidance_conf,
                "current_guidance_revenue_evidence": _text_value(event, "guidance_revenue_mid_evidence"),
                "guidance_revenue_mid": current_guidance,
                "guidance_revenue_low": event.get("guidance_revenue_low", np.nan),
                "guidance_revenue_high": event.get("guidance_revenue_high", np.nan),
                "prior_event_id": "" if prior is None else prior.get("event_id", ""),
                "prior_event_time": "" if prior is None or pd.isna(prior_event_time) else pd.Timestamp(prior_event_time).isoformat(),
                "prior_guidance_revenue_mid": prior_guidance,
                "prior_guidance_revenue_confidence": prior_guidance_conf,
                "prior_guidance_revenue_evidence": "" if prior is None else _text_value(prior, "guidance_revenue_mid_evidence"),
                "prior_event_gap_days": gap_days,
                "actual_vs_prior_management_guidance": surprise,
                "actual_vs_prior_management_guidance_pct": surprise_pct,
                "management_guidance_surprise_pct": surprise_pct,
                "new_guidance_vs_actual": new_guidance_vs_actual,
                "new_guidance_vs_actual_pct": new_guidance_vs_actual_pct,
                "actual_gross_margin": event.get("actual_gross_margin", np.nan),
                "actual_gross_margin_confidence": event.get("actual_gross_margin_confidence", np.nan),
                "guidance_gross_margin_mid": event.get("guidance_gross_margin_mid", np.nan),
                "guidance_gross_margin_mid_confidence": event.get("guidance_gross_margin_mid_confidence", np.nan),
                "parser_confidence_min": parser_confidence_min,
                "parser_quality_flags": ";".join(sorted(set(flags))),
                "bridge_status": status,
                "bridge_notes": "Management-guidance proxy uses current actual revenue vs immediately prior event guidance midpoint.",
                "model_eligible": status == READY_STATUS,
                "primary_surprise_metric": "actual_vs_prior_management_guidance_pct",
                "expectedness": "management_guidance_proxy_available" if status == READY_STATUS else "unknown",
                "surprise_direction": _direction(surprise_pct) if status == READY_STATUS else "unknown",
                "surprise_magnitude": _magnitude(surprise_pct) if status == READY_STATUS else "unknown",
            }
            rows.append(row)
            prior = event

    bridge = pd.DataFrame(rows)
    ensure_parent(out_path)
    bridge.to_csv(out_path, index=False)
    if failures_path:
        ensure_parent(failures_path)
        bridge[bridge["bridge_status"] != READY_STATUS].to_csv(failures_path, index=False)
    diag = BridgeDiagnostics(rows_total=int(len(bridge)))
    diag.events_with_actual_revenue = int(pd.to_numeric(bridge["actual_revenue"], errors="coerce").notna().sum()) if not bridge.empty else 0
    diag.events_with_current_guidance_revenue_mid = int(pd.to_numeric(bridge["current_guidance_revenue_mid"], errors="coerce").notna().sum()) if not bridge.empty else 0
    diag.events_with_prior_guidance_candidate = int(pd.to_numeric(bridge["prior_guidance_revenue_mid"], errors="coerce").notna().sum()) if not bridge.empty else 0
    diag.status_counts = bridge["bridge_status"].value_counts(dropna=False).to_dict() if not bridge.empty else {}
    diag.ready_for_model = int((bridge["bridge_status"] == READY_STATUS).sum()) if not bridge.empty else 0
    ready = bridge[bridge["bridge_status"] == READY_STATUS]
    diag.ready_by_ticker = ready["ticker"].value_counts().sort_index().to_dict() if not ready.empty else {}
    all_tickers = sorted(bridge["ticker"].dropna().unique().tolist()) if not bridge.empty else []
    ready_tickers = set(diag.ready_by_ticker)
    diag.tickers_with_zero_ready_rows = [ticker for ticker in all_tickers if ticker not in ready_tickers]
    ready_gaps = pd.to_numeric(ready["prior_event_gap_days"], errors="coerce") if not ready.empty else pd.Series(dtype=float)
    diag.median_prior_event_gap_days = float(ready_gaps.median()) if not ready_gaps.dropna().empty else None
    times = pd.to_datetime(bridge["event_time"], errors="coerce") if not bridge.empty else pd.Series(dtype="datetime64[ns]")
    if not times.dropna().empty:
        diag.date_range = {"start": times.min().date().isoformat(), "end": times.max().date().isoformat()}
    if diag.ready_for_model < 50:
        diag.warnings.append("Fewer than 50 ready bridge rows; do not model.")
    elif diag.ready_for_model < 80:
        diag.warnings.append("Bridge clears the minimum 50-row gate but misses the preferred 80-row gate.")
    if diag.ready_by_ticker:
        top_ticker, top_count = max(diag.ready_by_ticker.items(), key=lambda item: item[1])
        if top_count / max(diag.ready_for_model, 1) > 0.35:
            diag.warnings.append(f"Single ticker concentration exceeds 35%: {top_ticker} has {top_count} ready rows.")
    return bridge, diag


def _quantile_lines(values: pd.Series, label: str) -> list[str]:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return [f"- {label}: no values"]
    q = values.quantile([0, 0.25, 0.5, 0.75, 1.0])
    return [
        f"- {label} min: {q.loc[0]:.4f}",
        f"- {label} p25: {q.loc[0.25]:.4f}",
        f"- {label} median: {q.loc[0.5]:.4f}",
        f"- {label} p75: {q.loc[0.75]:.4f}",
        f"- {label} max: {q.loc[1.0]:.4f}",
    ]


def validate_management_guidance_bridge(
    bridge_path: str | Path,
    *,
    min_ready_rows: int = 50,
    preferred_ready_rows: int = 80,
    min_tickers: int = 6,
    max_single_ticker_share: float = 0.35,
    min_gap_days: int = 45,
    max_gap_days: int = 190,
    min_confidence: float = 0.80,
) -> dict:
    bridge = pd.read_csv(bridge_path)
    ready = bridge[bridge["bridge_status"] == READY_STATUS].copy()
    ready_count = int(len(ready))
    ready_by_ticker = ready["ticker"].value_counts().to_dict() if not ready.empty else {}
    max_share = max(ready_by_ticker.values()) / ready_count if ready_count else 0.0
    gaps = pd.to_numeric(ready.get("prior_event_gap_days", pd.Series(dtype=float)), errors="coerce")
    actual_conf = pd.to_numeric(ready.get("actual_revenue_confidence", pd.Series(dtype=float)), errors="coerce")
    prior_conf = pd.to_numeric(ready.get("prior_guidance_revenue_confidence", pd.Series(dtype=float)), errors="coerce")
    checks = {
        "ready_rows_minimum": ready_count >= min_ready_rows,
        "ready_rows_preferred": ready_count >= preferred_ready_rows,
        "actual_revenue_confidence": bool((actual_conf >= min_confidence).all()) if ready_count else False,
        "prior_guidance_revenue_confidence": bool((prior_conf >= min_confidence).all()) if ready_count else False,
        "prior_event_gap_bounds": bool(gaps.between(min_gap_days, max_gap_days, inclusive="both").all()) if ready_count else False,
        "ticker_count": len(ready_by_ticker) >= min_tickers,
        "single_ticker_concentration": max_share <= max_single_ticker_share if ready_count else False,
        "no_eps_dependency": not any("eps" in col.lower() for col in bridge.columns),
    }
    return {
        "ready_for_model_rows": ready_count,
        "ready_by_ticker": ready_by_ticker,
        "max_single_ticker_share": max_share,
        "checks": checks,
        "passed": bool(all(checks.values())),
    }


def write_management_guidance_validation_report(report: dict, out_path: str | Path) -> None:
    lines = [
        "# Management-Guidance Bridge Validation",
        "",
        f"- ready_for_model rows: {report['ready_for_model_rows']}",
        f"- max single ticker share: {report['max_single_ticker_share']:.3f}",
        f"- passed: {report['passed']}",
        "",
        "## Checks",
        "",
    ]
    for name, passed in report["checks"].items():
        lines.append(f"- {name}: {'PASS' if passed else 'FAIL'}")
    lines.extend(["", "## Ready Rows By Ticker", ""])
    for ticker, count in sorted(report["ready_by_ticker"].items()):
        lines.append(f"- {ticker}: {count}")
    ensure_parent(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_management_guidance_bridge_report(
    bridge: pd.DataFrame,
    diagnostics: BridgeDiagnostics,
    out_path: str | Path,
    *,
    min_ready_rows: int = 50,
    preferred_ready_rows: int = 80,
    min_oos_predictions: int = 30,
) -> None:
    ready = bridge[bridge["bridge_status"] == READY_STATUS].copy() if not bridge.empty else bridge.copy()
    likely_oos = max(0, len(ready) - 40)
    lines = [
        "# Agent 1D Report - Semiconductor Management-Guidance Bridge",
        "",
        "## Scope",
        "",
        "- No prediction or backtest was run.",
        "- Bridge compares current actual revenue to the immediately prior earnings event's revenue guidance midpoint.",
        "- Rows with implausible actual/prior ratios are flagged as `ambiguous` to avoid annual-period extraction mistakes.",
        "",
        "## Coverage",
        "",
        f"- total bridge rows: {diagnostics.rows_total}",
        f"- events with actual revenue: {diagnostics.events_with_actual_revenue}",
        f"- events with current guidance revenue midpoint: {diagnostics.events_with_current_guidance_revenue_mid}",
        f"- events with prior guidance candidate: {diagnostics.events_with_prior_guidance_candidate}",
        f"- ready_for_model rows: {diagnostics.ready_for_model}",
        f"- likely OOS predictions with min_train=40: {likely_oos}",
        f"- date range: {diagnostics.date_range.get('start', '')} to {diagnostics.date_range.get('end', '')}",
        f"- median prior event gap days: {diagnostics.median_prior_event_gap_days if diagnostics.median_prior_event_gap_days is not None else ''}",
        "",
        "## Status Counts",
        "",
    ]
    for status, count in diagnostics.status_counts.items():
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Ready Rows By Ticker", ""])
    for ticker, count in diagnostics.ready_by_ticker.items():
        lines.append(f"- {ticker}: {count}")
    if diagnostics.tickers_with_zero_ready_rows:
        lines.extend(["", "## Tickers With Zero Ready Rows", ""])
        for ticker in diagnostics.tickers_with_zero_ready_rows:
            lines.append(f"- {ticker}")

    negative = ready[pd.to_numeric(ready["actual_vs_prior_management_guidance_pct"], errors="coerce") <= -0.02]
    positive = ready[pd.to_numeric(ready["actual_vs_prior_management_guidance_pct"], errors="coerce") >= 0.02]
    neutral = ready[
        pd.to_numeric(ready["actual_vs_prior_management_guidance_pct"], errors="coerce").between(-0.02, 0.02, inclusive="neither")
    ]
    lines.extend(
        [
            "",
            "## Surprise Buckets",
            "",
            f"- negative <= -2%: {len(negative)}",
            f"- positive >= +2%: {len(positive)}",
            f"- neutral between -2% and +2%: {len(neutral)}",
            "",
            "## Distribution",
            "",
            *_quantile_lines(ready.get("actual_vs_prior_management_guidance_pct", pd.Series(dtype=float)), "actual_vs_prior_management_guidance_pct"),
            *_quantile_lines(ready.get("new_guidance_vs_actual_pct", pd.Series(dtype=float)), "new_guidance_vs_actual_pct"),
            "",
            "## Extremes",
            "",
            "### Top Positive Management-Guidance Beats",
            "",
        ]
    )
    top_cols = ["event_id", "ticker", "event_time", "actual_vs_prior_management_guidance_pct"]
    top_positive = ready.sort_values("actual_vs_prior_management_guidance_pct", ascending=False).head(10) if not ready.empty else ready
    for _, row in top_positive.iterrows():
        lines.append(
            f"- {row.get('ticker', '')} {row.get('event_time', '')}: "
            f"{pd.to_numeric(row.get('actual_vs_prior_management_guidance_pct'), errors='coerce'):.4f} "
            f"({row.get('event_id', '')})"
        )
    lines.extend(["", "### Top Negative Management-Guidance Misses", ""])
    top_negative = ready.sort_values("actual_vs_prior_management_guidance_pct", ascending=True).head(10) if not ready.empty else ready
    for _, row in top_negative.iterrows():
        lines.append(
            f"- {row.get('ticker', '')} {row.get('event_time', '')}: "
            f"{pd.to_numeric(row.get('actual_vs_prior_management_guidance_pct'), errors='coerce'):.4f} "
            f"({row.get('event_id', '')})"
        )
    lines.extend(
        [
            "",
            "## Gates",
            "",
            f"- ready rows >= {min_ready_rows}: {'PASS' if diagnostics.ready_for_model >= min_ready_rows else 'FAIL'}",
            f"- preferred ready rows >= {preferred_ready_rows}: {'PASS' if diagnostics.ready_for_model >= preferred_ready_rows else 'FAIL'}",
            f"- likely OOS predictions >= {min_oos_predictions}: {'PASS' if likely_oos >= min_oos_predictions else 'FAIL'}",
            "",
            "## Decision",
            "",
        ]
    )
    if diagnostics.ready_for_model >= min_ready_rows and likely_oos >= min_oos_predictions:
        lines.append("**Continue to a cautious model run.**")
    elif diagnostics.ready_for_model >= min_ready_rows:
        lines.append("**Continue data buildout; do not model yet under the standard gate.**")
    else:
        lines.append("**Do not model. Bridge coverage is still too thin.**")
    lines.extend(["", "## Warnings", ""])
    if diagnostics.warnings:
        for warning in diagnostics.warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- None.")
    ensure_parent(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
