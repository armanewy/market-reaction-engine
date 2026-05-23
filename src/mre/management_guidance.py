from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re

import numpy as np
import pandas as pd

from .paths import ensure_parent


READY_STATUS = "ready_for_model"
ALIGNED_PERIOD_STATUSES = {"aligned", "inferred_aligned"}
QUARTER_WORDS = {
    "first": 1,
    "1st": 1,
    "q1": 1,
    "second": 2,
    "2nd": 2,
    "q2": 2,
    "third": 3,
    "3rd": 3,
    "q3": 3,
    "fourth": 4,
    "4th": 4,
    "q4": 4,
}


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


def _period_label(year: int | float | None, quarter: int | float | None) -> str:
    if pd.isna(year) or pd.isna(quarter):
        return ""
    return f"FY{int(year)}Q{int(quarter)}"


def _previous_fiscal_quarter(year: int, quarter: int) -> tuple[int, int]:
    if quarter == 1:
        return year - 1, 4
    return year, quarter - 1


def _quarter_from_token(token: str) -> int | None:
    token = token.lower().strip()
    if token.isdigit() and token in {"1", "2", "3", "4"}:
        return int(token)
    return QUARTER_WORDS.get(token)


def _full_year_text(text: str) -> bool:
    lower = text.lower()
    return bool(
        re.search(r"\bfiscal\s+(?:year\s+)?\d{4}\s+revenue\b", lower)
        or re.search(r"\bfull[-\s]?year\b", lower)
        or re.search(r"\byear\s+ended\b", lower)
        or re.search(r"\bannual\b", lower)
    )


def _parse_fiscal_period(text: str) -> tuple[int, int, str] | None:
    lower = text.lower()
    q_tokens = r"first|1st|second|2nd|third|3rd|fourth|4th|q[1-4]"
    patterns = [
        rf"\b({q_tokens})\s+quarter\s+(?:of\s+)?(?:fiscal\s+)?(?:year\s+)?(\d{{4}})\b",
        rf"\b(?:fiscal\s+)?(?:year\s+)?(\d{{4}})\s+({q_tokens})\s+quarter\b",
        r"\bq([1-4])\s+(?:fiscal\s+)?(?:year\s+)?(\d{4})\b",
        r"\b(?:fiscal\s+)?(?:year\s+)?(\d{4})\s+q([1-4])\b",
    ]
    for idx, pattern in enumerate(patterns):
        match = re.search(pattern, lower)
        if not match:
            continue
        if idx in {0, 2}:
            q_token, year_token = match.group(1), match.group(2)
        else:
            year_token, q_token = match.group(1), match.group(2)
        quarter = _quarter_from_token(q_token)
        if quarter is None:
            continue
        return int(year_token), quarter, match.group(0)
    return None


def _infer_period_alignment(event: pd.Series, prior: pd.Series | None, gap_days: float) -> dict:
    actual_evidence = _text_value(event, "actual_revenue_evidence")
    current_guidance_evidence = _text_value(event, "guidance_revenue_mid_evidence")
    prior_guidance_evidence = "" if prior is None else _text_value(prior, "guidance_revenue_mid_evidence")

    current_target = _parse_fiscal_period(current_guidance_evidence)
    prior_target = _parse_fiscal_period(prior_guidance_evidence)
    actual_period = _parse_fiscal_period(actual_evidence)
    actual_is_full_year = actual_period is None and _full_year_text(actual_evidence)

    current_reported = actual_period
    current_source = "actual_revenue_evidence"
    notes: list[str] = []
    if actual_is_full_year:
        notes.append("actual revenue evidence appears to describe a full-year period")
    if current_reported is None and current_target is not None:
        year, quarter = _previous_fiscal_quarter(current_target[0], current_target[1])
        current_reported = (year, quarter, f"inferred from current guidance target {current_target[2]}")
        current_source = "current_guidance_target_minus_one_quarter"
    elif current_reported is None and prior_target is not None and not pd.isna(gap_days) and 70 <= float(gap_days) <= 120:
        current_reported = (prior_target[0], prior_target[1], f"inferred from prior guidance target {prior_target[2]}")
        current_source = "prior_guidance_target_with_quarterly_gap"

    if actual_is_full_year:
        status = "rejected"
    elif prior_target is not None and current_reported is not None:
        status = "aligned" if (prior_target[0], prior_target[1]) == (current_reported[0], current_reported[1]) else "ambiguous"
        if status == "ambiguous":
            notes.append("prior guidance target period does not match inferred current reported period")
    elif not pd.isna(gap_days) and 70 <= float(gap_days) <= 120:
        status = "inferred_aligned"
        notes.append("period inferred from normal quarterly event gap")
    else:
        status = "ambiguous"
        notes.append("insufficient fiscal-period evidence")

    return {
        "current_reported_period_text": "" if current_reported is None else current_reported[2],
        "current_reported_fiscal_year": np.nan if current_reported is None else current_reported[0],
        "current_reported_fiscal_quarter": np.nan if current_reported is None else current_reported[1],
        "current_reported_period_label": "" if current_reported is None else _period_label(current_reported[0], current_reported[1]),
        "current_reported_period_source": current_source if current_reported is not None else "",
        "prior_guidance_target_period_text": "" if prior_target is None else prior_target[2],
        "prior_guidance_target_fiscal_year": np.nan if prior_target is None else prior_target[0],
        "prior_guidance_target_fiscal_quarter": np.nan if prior_target is None else prior_target[1],
        "prior_guidance_target_period_label": "" if prior_target is None else _period_label(prior_target[0], prior_target[1]),
        "period_alignment_status": status,
        "period_alignment_notes": "; ".join(notes),
    }


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
    require_period_alignment: bool = True,
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
            period = _infer_period_alignment(event, prior, gap_days)
            if status == READY_STATUS and require_period_alignment and period["period_alignment_status"] not in ALIGNED_PERIOD_STATUSES:
                status = "period_ambiguous"
                flags.append(f"period_alignment_{period['period_alignment_status']}")

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
            current_guidance_vs_prior_guidance = np.nan
            current_guidance_vs_prior_guidance_pct = np.nan
            if not pd.isna(current_guidance) and not pd.isna(prior_guidance) and prior_guidance:
                current_guidance_vs_prior_guidance = float(current_guidance) - float(prior_guidance)
                current_guidance_vs_prior_guidance_pct = current_guidance_vs_prior_guidance / abs(float(prior_guidance))

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
                **period,
                "actual_vs_prior_management_guidance": surprise,
                "actual_vs_prior_management_guidance_pct": surprise_pct,
                "management_guidance_surprise_pct": surprise_pct,
                "new_guidance_vs_actual": new_guidance_vs_actual,
                "new_guidance_vs_actual_pct": new_guidance_vs_actual_pct,
                "new_guidance_vs_current_actual_pct": new_guidance_vs_actual_pct,
                "current_guidance_vs_prior_guidance": current_guidance_vs_prior_guidance,
                "current_guidance_vs_prior_guidance_pct": current_guidance_vs_prior_guidance_pct,
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
    for value_col, rank_col in [
        ("actual_vs_prior_management_guidance_pct", "actual_vs_prior_guidance_rank_by_ticker"),
        ("current_guidance_vs_prior_guidance_pct", "current_guidance_vs_prior_guidance_rank_by_ticker"),
    ]:
        values = pd.to_numeric(bridge[value_col], errors="coerce")
        bridge[rank_col] = values.groupby(bridge["ticker"]).rank(pct=True)
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
    period_status = ready.get("period_alignment_status", pd.Series(dtype=str)).astype(str)
    checks = {
        "ready_rows_minimum": ready_count >= min_ready_rows,
        "ready_rows_preferred": ready_count >= preferred_ready_rows,
        "actual_revenue_confidence": bool((actual_conf >= min_confidence).all()) if ready_count else False,
        "prior_guidance_revenue_confidence": bool((prior_conf >= min_confidence).all()) if ready_count else False,
        "prior_event_gap_bounds": bool(gaps.between(min_gap_days, max_gap_days, inclusive="both").all()) if ready_count else False,
        "period_alignment_non_ambiguous": bool(period_status.isin(ALIGNED_PERIOD_STATUSES).all()) if ready_count else False,
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


def write_management_guidance_period_audit(bridge: pd.DataFrame, out_path: str | Path) -> None:
    cols = [
        "event_id",
        "ticker",
        "event_time",
        "bridge_status",
        "model_eligible",
        "current_reported_period_label",
        "current_reported_period_text",
        "current_reported_period_source",
        "prior_guidance_target_period_label",
        "prior_guidance_target_period_text",
        "period_alignment_status",
        "period_alignment_notes",
        "actual_revenue",
        "actual_revenue_evidence",
        "prior_guidance_revenue_mid",
        "prior_guidance_revenue_evidence",
        "current_guidance_revenue_mid",
        "current_guidance_revenue_evidence",
        "prior_event_gap_days",
        "parser_quality_flags",
    ]
    ensure_parent(out_path)
    bridge[[c for c in cols if c in bridge.columns]].to_csv(out_path, index=False)


def _threshold_count_lines(ready: pd.DataFrame, col: str) -> list[str]:
    values = pd.to_numeric(ready.get(col, pd.Series(dtype=float)), errors="coerce")
    lines: list[str] = []
    for threshold in [-0.005, -0.01, -0.02]:
        lines.append(f"- {col} <= {threshold:.3f}: {int((values <= threshold).sum())}")
    for threshold in [0.005, 0.01, 0.02]:
        lines.append(f"- {col} >= +{threshold:.3f}: {int((values >= threshold).sum())}")
    return lines


def _bucket_stats(merged: pd.DataFrame, mask: pd.Series, label: str) -> list[str]:
    h1 = pd.to_numeric(merged.get("car_sector_adj_h1", pd.Series(dtype=float)), errors="coerce")
    h3 = pd.to_numeric(merged.get("car_sector_adj_h3", pd.Series(dtype=float)), errors="coerce")
    count = int(mask.sum())
    if count == 0:
        return [f"- {label}: n=0"]
    return [
        f"- {label}: n={count}, mean_h1={h1[mask].mean():.4f}, mean_h3={h3[mask].mean():.4f}",
    ]


def _top_fix_candidates(bridge: pd.DataFrame) -> pd.DataFrame:
    non_ready = bridge[bridge["bridge_status"] != READY_STATUS].copy()
    if non_ready.empty:
        return non_ready
    actual = pd.to_numeric(non_ready.get("actual_revenue", pd.Series(dtype=float)), errors="coerce")
    prior = pd.to_numeric(non_ready.get("prior_guidance_revenue_mid", pd.Series(dtype=float)), errors="coerce")
    current_guidance = pd.to_numeric(non_ready.get("current_guidance_revenue_mid", pd.Series(dtype=float)), errors="coerce")
    score = pd.Series(0, index=non_ready.index, dtype=int)
    score += actual.notna().astype(int)
    score += prior.notna().astype(int)
    score += current_guidance.notna().astype(int)
    score += non_ready["bridge_status"].isin(["missing_actual_revenue", "missing_prior_guidance", "period_ambiguous"]).astype(int)
    non_ready["_fix_score"] = score
    return non_ready.sort_values(["_fix_score", "ticker", "event_time"], ascending=[False, True, True]).head(20)


def write_management_guidance_expansion_report(
    bridge: pd.DataFrame,
    diagnostics: BridgeDiagnostics,
    out_path: str | Path,
    *,
    event_study_path: str | Path | None = None,
) -> None:
    ready = bridge[bridge["bridge_status"] == READY_STATUS].copy() if not bridge.empty else bridge.copy()
    lines = [
        "# Agent 1D4 Expansion Report - Management-Guidance Bridge",
        "",
        "## Decision",
        "",
        "**Do not model yet. Expand and validate the bridge.**",
        "",
        "## Failure Triage",
        "",
    ]
    for status, count in diagnostics.status_counts.items():
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Bridge Readiness", ""])
    lines.append(f"- ready_for_model rows: {diagnostics.ready_for_model}")
    lines.append(f"- ready tickers: {len(diagnostics.ready_by_ticker)}")
    lines.append(f"- likely OOS predictions with min_train=40: {max(0, diagnostics.ready_for_model - 40)}")
    lines.append(f"- top ticker share: {max(diagnostics.ready_by_ticker.values()) / diagnostics.ready_for_model:.3f}" if diagnostics.ready_for_model else "- top ticker share: n/a")
    lines.extend(["", "## Ready Rows By Ticker", ""])
    for ticker, count in diagnostics.ready_by_ticker.items():
        lines.append(f"- {ticker}: {count}")
    lines.extend(["", "## Period Alignment", ""])
    if "period_alignment_status" in bridge.columns:
        for status, count in bridge["period_alignment_status"].value_counts(dropna=False).to_dict().items():
            lines.append(f"- {status}: {count}")
    lines.extend(["", "## Threshold Counts", ""])
    lines.extend(_threshold_count_lines(ready, "actual_vs_prior_management_guidance_pct"))
    lines.extend(["", "## Forward-Guidance Delta Counts", ""])
    lines.extend(_threshold_count_lines(ready, "current_guidance_vs_prior_guidance_pct"))
    lines.extend(_threshold_count_lines(ready, "new_guidance_vs_current_actual_pct"))

    if event_study_path and Path(event_study_path).exists() and not ready.empty:
        event_study = pd.read_csv(event_study_path)
        merged = ready.merge(event_study, on="event_id", how="left", suffixes=("", "_event_study"))
        runup = pd.to_numeric(merged.get("market_adjusted_pre_return_20d", pd.Series(dtype=float)), errors="coerce")
        surprise = pd.to_numeric(merged.get("actual_vs_prior_management_guidance_pct", pd.Series(dtype=float)), errors="coerce")
        guidance_delta = pd.to_numeric(merged.get("current_guidance_vs_prior_guidance_pct", pd.Series(dtype=float)), errors="coerce")
        h1 = pd.to_numeric(merged.get("car_sector_adj_h1", pd.Series(dtype=float)), errors="coerce")
        h3 = pd.to_numeric(merged.get("car_sector_adj_h3", pd.Series(dtype=float)), errors="coerce")
        lines.extend(["", "## Descriptive Market Context", ""])
        lines.append(f"- ready rows with positive 20d market-adjusted run-up: {int((runup > 0).sum())}")
        lines.append(f"- mean surprise pct after positive run-up: {surprise[runup > 0].mean():.4f}" if (runup > 0).any() else "- mean surprise pct after positive run-up: n/a")
        lines.append(f"- mean h1 sector-adjusted abnormal return: {h1.mean():.4f}" if h1.notna().any() else "- mean h1 sector-adjusted abnormal return: n/a")
        lines.append(f"- mean h3 sector-adjusted abnormal return: {h3.mean():.4f}" if h3.notna().any() else "- mean h3 sector-adjusted abnormal return: n/a")
        miss_1 = surprise <= -0.01
        lines.append(f"- h1 sector-adjusted return for <= -1% management-guidance misses: {h1[miss_1].mean():.4f}" if miss_1.any() else "- h1 sector-adjusted return for <= -1% management-guidance misses: n/a")
        lines.append(f"- h3 sector-adjusted return for <= -1% management-guidance misses: {h3[miss_1].mean():.4f}" if miss_1.any() else "- h3 sector-adjusted return for <= -1% management-guidance misses: n/a")
        pos_runup = runup > 0
        no_runup = runup <= 0
        beat = surprise >= 0.005
        miss = surprise <= -0.005
        guide_raise = guidance_delta >= 0.005
        guide_cut = guidance_delta <= -0.005
        lines.extend(["", "## Pre-Registered Descriptive Buckets", ""])
        for bucket_lines in [
            _bucket_stats(merged, pos_runup & beat, "positive run-up + positive management beat"),
            _bucket_stats(merged, pos_runup & miss, "positive run-up + negative management miss"),
            _bucket_stats(merged, pos_runup & guide_cut, "positive run-up + current guidance cut"),
            _bucket_stats(merged, pos_runup & guide_raise, "positive run-up + current guidance raise"),
            _bucket_stats(merged, no_runup & beat, "no run-up + positive management beat"),
            _bucket_stats(merged, no_runup & guide_raise, "no run-up + current guidance raise"),
        ]:
            lines.extend(bucket_lines)

    candidates = _top_fix_candidates(bridge)
    lines.extend(["", "## Top Fix Candidates", ""])
    if candidates.empty:
        lines.append("- None.")
    else:
        for _, row in candidates.iterrows():
            lines.append(
                f"- {row.get('ticker', '')} {row.get('event_time', '')} {row.get('bridge_status', '')}: "
                f"{row.get('event_id', '')}"
            )
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
            *_quantile_lines(ready.get("current_guidance_vs_prior_guidance_pct", pd.Series(dtype=float)), "current_guidance_vs_prior_guidance_pct"),
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
