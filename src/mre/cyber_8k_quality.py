from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .paths import ensure_parent


BOOLEAN_FIELDS = (
    "ransomware_mentioned",
    "customer_data_exposure_mentioned",
    "operational_disruption_mentioned",
    "third_party_vendor_mentioned",
    "no_material_impact_language",
    "impact_unknown_or_not_determined",
    "reasonably_likely_material_impact_language",
)


def _load_frame(value: str | Path | pd.DataFrame | None) -> pd.DataFrame:
    if value is None:
        return pd.DataFrame()
    if isinstance(value, pd.DataFrame):
        return value.copy()
    return pd.read_csv(value)


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return _clean_value(value)


def _nonempty(series: pd.Series) -> pd.Series:
    return series.notna() & (series.astype(str).str.strip() != "")


def _bool_series(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).str.strip().str.lower()
    return text.isin({"1", "true", "yes", "y"})


def _status_counts(df: pd.DataFrame, column: str) -> dict[str, int]:
    if df.empty or column not in df.columns:
        return {}
    counts = df[column].fillna("missing").astype(str).str.strip().replace("", "missing").value_counts().sort_index()
    return {str(k): int(v) for k, v in counts.items()}


def _claim_status_frame(claims: pd.DataFrame, review_queue: pd.DataFrame) -> pd.DataFrame:
    if not review_queue.empty:
        return review_queue.copy()
    return claims.copy()


def _evidence_present(claims: pd.DataFrame, evidence: pd.DataFrame, review_queue: pd.DataFrame) -> pd.Series:
    if not review_queue.empty and "evidence_present" in review_queue.columns:
        return _bool_series(review_queue["evidence_present"])
    if claims.empty:
        return pd.Series(dtype=bool)
    if "evidence_span_id" not in claims.columns:
        return pd.Series(False, index=claims.index)
    claim_has_span = _nonempty(claims["evidence_span_id"])
    if evidence.empty or "evidence_span_id" not in evidence.columns:
        return claim_has_span
    evidence_ids = set(evidence["evidence_span_id"].dropna().astype(str))
    return claim_has_span & claims["evidence_span_id"].astype(str).isin(evidence_ids)


def _company_count(events: pd.DataFrame) -> int:
    for column in ("ticker", "cik", "company_name"):
        if column in events.columns:
            values = events[column].dropna().astype(str).str.strip()
            values = values[values != ""]
            if not values.empty:
                return int(values.nunique())
    return 0


def _field_counts(claims: pd.DataFrame, total_events: int) -> list[dict[str, Any]]:
    if claims.empty or "field_name" not in claims.columns:
        return []
    rows: list[dict[str, Any]] = []
    for field, group in claims.groupby("field_name", dropna=False):
        values = group.get("confidence", pd.Series(dtype=float))
        confidence = pd.to_numeric(values, errors="coerce")
        rows.append(
            {
                "field_name": str(field),
                "claims": int(len(group)),
                "event_coverage_rate": float(group["event_id"].nunique() / total_events) if total_events and "event_id" in group.columns else None,
                "average_confidence": None if confidence.dropna().empty else float(confidence.mean()),
            }
        )
    return sorted(rows, key=lambda row: row["field_name"])


def _field_review_rates(status_df: pd.DataFrame) -> list[dict[str, Any]]:
    if status_df.empty or "field_name" not in status_df.columns:
        return []
    rows: list[dict[str, Any]] = []
    for field, group in status_df.groupby("field_name", dropna=False):
        statuses = group.get("review_status", pd.Series("", index=group.index)).fillna("").astype(str).str.lower()
        rejected = int((statuses == "rejected").sum())
        needs_review = int(statuses.isin({"needs_review", "missing_evidence", ""}).sum())
        rows.append(
            {
                "field_name": str(field),
                "claims": int(len(group)),
                "rejected": rejected,
                "needs_review": needs_review,
                "rejected_rate": float(rejected / len(group)) if len(group) else 0.0,
                "needs_review_rate": float(needs_review / len(group)) if len(group) else 0.0,
            }
        )
    return sorted(rows, key=lambda row: row["field_name"])


def _amendment_coverage(events: pd.DataFrame) -> dict[str, Any]:
    coverage: dict[str, Any] = {}
    if "amended_later" in events.columns:
        amended = _bool_series(events["amended_later"])
        coverage["events_amended_later"] = int(amended.sum())
        coverage["events_amended_later_rate"] = float(amended.mean()) if len(amended) else 0.0
    if "amendment_count" in events.columns:
        counts = pd.to_numeric(events["amendment_count"], errors="coerce").fillna(0)
        coverage["events_with_amendment_count"] = int((counts > 0).sum())
        coverage["total_amendments"] = int(counts.sum())
    if "amendment_flag" in events.columns:
        flags = _bool_series(events["amendment_flag"])
        coverage["amendment_event_rows"] = int(flags.sum())
    return coverage


def _warnings(
    *,
    review_coverage_rate: float,
    n_missing_evidence_claims: int,
    needs_review_rate: float,
    timestamp_counts: dict[str, int],
    field_review_rates: list[dict[str, Any]],
) -> list[str]:
    warnings: list[str] = []
    if review_coverage_rate < 0.8:
        warnings.append("low_review_coverage")
    if n_missing_evidence_claims:
        warnings.append("missing_evidence")
    if needs_review_rate > 0.5:
        warnings.append("high_needs_review_rate")
    non_ok_timestamps = sum(count for status, count in timestamp_counts.items() if str(status).lower() not in {"ok", "ready"})
    if non_ok_timestamps:
        warnings.append("unknown_or_non_ok_timestamp_readiness")
    high_rejection_fields = [row["field_name"] for row in field_review_rates if row["claims"] >= 2 and row["rejected_rate"] >= 0.25]
    if high_rejection_fields:
        warnings.append("high_rejection_rate_fields:" + ",".join(high_rejection_fields))
    return warnings


def _markdown_report(report: dict[str, Any]) -> str:
    field_rows = report["field_coverage_by_field_name"]
    field_lines = [
        "| Field | Claims | Event Coverage | Avg Confidence |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in field_rows:
        coverage = "" if row["event_coverage_rate"] is None else f"{row['event_coverage_rate']:.2%}"
        confidence = "" if row["average_confidence"] is None else f"{row['average_confidence']:.2f}"
        field_lines.append(f"| {row['field_name']} | {row['claims']} | {coverage} | {confidence} |")
    warnings = report.get("warnings", [])
    warning_lines = "\n".join(f"- {warning}" for warning in warnings) if warnings else "- none"
    return "\n".join(
        [
            "# Cyber 8-K Quality Report",
            "",
            "## Summary",
            "",
            f"- Events: {report['n_events']}",
            f"- Companies: {report['n_companies']}",
            f"- Claims: {report['n_claims']}",
            f"- Evidence spans: {report['n_evidence_spans']}",
            f"- Review coverage: {report['review_coverage_rate']:.2%}",
            f"- Evidence coverage: {report['evidence_coverage_rate']:.2%}",
            "",
            "## Review Status",
            "",
            f"- Reviewed claims: {report['n_reviewed_claims']}",
            f"- Rejected claims: {report['n_rejected_claims']}",
            f"- Needs review claims: {report['n_needs_review_claims']}",
            "",
            "## Warnings",
            "",
            warning_lines,
            "",
            "## Field Coverage",
            "",
            "\n".join(field_lines),
            "",
        ]
    )


def build_cyber_8k_quality_report(
    events_csv,
    claims_csv,
    evidence_spans_csv,
    review_queue_csv=None,
    *,
    out_json=None,
    out_md=None,
) -> dict[str, Any]:
    events = _load_frame(events_csv)
    claims = _load_frame(claims_csv)
    evidence = _load_frame(evidence_spans_csv)
    review_queue = _load_frame(review_queue_csv)
    status_df = _claim_status_frame(claims, review_queue)

    evidence_present = _evidence_present(claims, evidence, review_queue)
    n_claims = int(len(claims))
    n_missing_evidence_claims = int((~evidence_present).sum()) if len(evidence_present) else 0
    statuses = status_df.get("review_status", pd.Series("", index=status_df.index)).fillna("").astype(str).str.lower()
    n_reviewed = int(statuses.isin({"reviewed", "approved"}).sum())
    n_rejected = int((statuses == "rejected").sum())
    n_needs_review = int(statuses.isin({"needs_review", "missing_evidence", ""}).sum())
    timestamp_counts = _status_counts(events, "timestamp_readiness_status")
    field_review_rates = _field_review_rates(status_df)

    report = {
        "n_events": int(len(events)),
        "n_companies": _company_count(events),
        "n_claims": n_claims,
        "n_evidence_spans": int(len(evidence)),
        "n_reviewed_claims": n_reviewed,
        "n_rejected_claims": n_rejected,
        "n_needs_review_claims": n_needs_review,
        "n_missing_evidence_claims": n_missing_evidence_claims,
        "evidence_coverage_rate": float((n_claims - n_missing_evidence_claims) / n_claims) if n_claims else 0.0,
        "review_coverage_rate": float(n_reviewed / len(status_df)) if len(status_df) else 0.0,
        "needs_review_rate": float(n_needs_review / len(status_df)) if len(status_df) else 0.0,
        "field_coverage_by_field_name": _field_counts(claims, int(len(events))),
        "field_review_rates_by_field_name": field_review_rates,
        "timestamp_readiness_status_counts": timestamp_counts,
        "event_review_status_counts": _status_counts(events, "event_review_status"),
        "amendment_coverage": _amendment_coverage(events),
    }
    report["warnings"] = _warnings(
        review_coverage_rate=report["review_coverage_rate"],
        n_missing_evidence_claims=n_missing_evidence_claims,
        needs_review_rate=report["needs_review_rate"],
        timestamp_counts=timestamp_counts,
        field_review_rates=field_review_rates,
    )
    report = _jsonable(report)

    if out_json:
        path = ensure_parent(out_json)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if out_md:
        path = ensure_parent(out_md)
        path.write_text(_markdown_report(report), encoding="utf-8")
    return report
