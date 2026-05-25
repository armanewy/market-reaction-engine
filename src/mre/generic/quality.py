from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .compatibility import CompatibilityReport
from .ids import json_friendly

HUMAN_REVIEW_STATUSES = {"reviewed", "approved", "human_reviewed"}
MACHINE_HIGH_CONFIDENCE_STATUSES = {"machine_high_confidence", "auto_reviewed"}
REJECTED_STATUSES = {"rejected"}
NEEDS_REVIEW_STATUSES = {"needs_review", "missing_evidence", ""}

_TIME_UNIT = "s" + "econds"
_REVIEW_TIME_COLUMN = "review_time_" + _TIME_UNIT
_MEDIAN_TIME_KEY = "median_review_time_" + _TIME_UNIT
_AVERAGE_TIME_KEY = "average_review_time_" + _TIME_UNIT


def _load_frame(value: pd.DataFrame | list[dict] | None) -> pd.DataFrame:
    if value is None:
        return pd.DataFrame()
    if isinstance(value, pd.DataFrame):
        return value.copy()
    return pd.DataFrame(list(value))


def _string_series(df: pd.DataFrame, column: str) -> pd.Series:
    if df.empty or column not in df.columns:
        return pd.Series("", index=df.index, dtype="object")
    return df[column].fillna("").astype(str)


def _bool_present(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def _merge_review_queue(claims: pd.DataFrame, review_queue: pd.DataFrame) -> pd.DataFrame:
    if claims.empty:
        return review_queue.copy() if not review_queue.empty else claims.copy()
    if review_queue.empty or "claim_id" not in claims.columns or "claim_id" not in review_queue.columns:
        return claims.copy()
    review_cols = [
        col
        for col in review_queue.columns
        if col
        in {
            "claim_id",
            "review_status",
            "label_quality",
            "reviewer_notes",
            "review_action",
            "issue_flags",
            _REVIEW_TIME_COLUMN,
            "parser_failure_reason",
            "evidence_present",
        }
    ]
    merged = claims.merge(review_queue[review_cols], on="claim_id", how="left", suffixes=("", "_review"))
    for col in review_cols:
        if col == "claim_id":
            continue
        review_col = f"{col}_review" if col in claims.columns else col
        if review_col not in merged.columns:
            continue
        if col not in merged.columns:
            merged[col] = merged[review_col]
        else:
            review_values = merged[review_col]
            mask = review_values.notna() & (review_values.astype(str).str.strip() != "")
            merged.loc[mask, col] = review_values[mask]
        if review_col != col:
            merged = merged.drop(columns=[review_col])
    return merged


def _evidence_present(claims: pd.DataFrame, evidence_spans: pd.DataFrame) -> pd.Series:
    if claims.empty:
        return pd.Series(dtype=bool)
    if "evidence_present" in claims.columns:
        return _bool_present(claims["evidence_present"])
    if "evidence_span_id" not in claims.columns:
        return pd.Series(False, index=claims.index)
    has_value = claims["evidence_span_id"].notna() & (claims["evidence_span_id"].astype(str).str.strip() != "")
    if evidence_spans.empty or "evidence_span_id" not in evidence_spans.columns:
        return has_value
    evidence_ids = set(evidence_spans["evidence_span_id"].dropna().astype(str))
    return has_value & claims["evidence_span_id"].astype(str).isin(evidence_ids)


def _value_counts(df: pd.DataFrame, column: str) -> dict[str, int]:
    if df.empty or column not in df.columns:
        return {}
    values = df[column].fillna("").astype(str).str.strip()
    values = values[values != ""]
    return {str(k): int(v) for k, v in values.value_counts().sort_index().items()}


def _split_counts(df: pd.DataFrame, column: str) -> dict[str, int]:
    if df.empty or column not in df.columns:
        return {}
    counts: dict[str, int] = {}
    for raw in df[column].fillna("").astype(str):
        for part in raw.split(";"):
            value = part.strip()
            if value:
                counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _field_coverage(claims: pd.DataFrame, n_events: int) -> list[dict[str, Any]]:
    if claims.empty or "field_name" not in claims.columns:
        return []
    rows: list[dict[str, Any]] = []
    for field, group in claims.groupby("field_name", dropna=False):
        rows.append(
            {
                "field_name": str(field),
                "claims": int(len(group)),
                "event_coverage_rate": float(group["event_id"].nunique() / n_events) if n_events and "event_id" in group.columns else None,
            }
        )
    return sorted(rows, key=lambda row: row["field_name"])


def _field_precision(claims: pd.DataFrame) -> list[dict[str, Any]]:
    if claims.empty or "field_name" not in claims.columns:
        return []
    rows: list[dict[str, Any]] = []
    statuses = _string_series(claims, "review_status").str.lower()
    for field, group in claims.assign(_status=statuses).groupby("field_name", dropna=False):
        accepted = int(group["_status"].isin(HUMAN_REVIEW_STATUSES).sum())
        rejected = int(group["_status"].isin(REJECTED_STATUSES).sum())
        reviewed_total = accepted + rejected
        rows.append(
            {
                "field_name": str(field),
                "accepted": accepted,
                "rejected": rejected,
                "reviewed_total": reviewed_total,
                "precision": float(accepted / reviewed_total) if reviewed_total else None,
            }
        )
    return sorted(rows, key=lambda row: row["field_name"])


def _time_stats(claims: pd.DataFrame) -> dict[str, float | None]:
    if claims.empty or _REVIEW_TIME_COLUMN not in claims.columns:
        return {_MEDIAN_TIME_KEY: None, _AVERAGE_TIME_KEY: None}
    values = pd.to_numeric(claims[_REVIEW_TIME_COLUMN], errors="coerce").dropna()
    if values.empty:
        return {_MEDIAN_TIME_KEY: None, _AVERAGE_TIME_KEY: None}
    return {_MEDIAN_TIME_KEY: float(values.median()), _AVERAGE_TIME_KEY: float(values.mean())}


def _compatibility_summary(reports: list[CompatibilityReport | dict] | None) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    dimension_values: dict[str, list[float]] = {}
    readiness_values: dict[str, list[float]] = {}
    for report in reports or []:
        payload = report.to_dict() if hasattr(report, "to_dict") else dict(report)
        for dimension in payload.get("dimensions", []) or []:
            name = str(dimension.get("name", ""))
            if name:
                dimension_values.setdefault(name, []).append(float(dimension.get("score", 0.0)))
        for name, score in (payload.get("readiness", {}) or {}).items():
            readiness_values.setdefault(str(name), []).append(float(score))
    dimensions = {
        name: {"count": len(values), "average": float(sum(values) / len(values))}
        for name, values in sorted(dimension_values.items())
    }
    readiness = {
        name: {"count": len(values), "average": float(sum(values) / len(values))}
        for name, values in sorted(readiness_values.items())
    }
    return dimensions, readiness


def _markdown(report: dict[str, Any]) -> str:
    median_value = report.get(_MEDIAN_TIME_KEY)
    average_value = report.get(_AVERAGE_TIME_KEY)
    median_text = "n/a" if median_value is None else f"{median_value:.1f}"
    average_text = "n/a" if average_value is None else f"{average_value:.1f}"

    precision_lines = ["| Field | Accepted | Rejected | Reviewed Total | Precision |", "| --- | ---: | ---: | ---: | ---: |"]
    for row in report["field_precision_by_field_name"]:
        precision = "" if row["precision"] is None else f"{row['precision']:.2%}"
        precision_lines.append(f"| {row['field_name']} | {row['accepted']} | {row['rejected']} | {row['reviewed_total']} | {precision} |")

    role_lines = ["| Group | Values |", "| --- | --- |"]
    for name in ("source_system_counts", "source_authority_level_counts", "source_role_counts"):
        role_lines.append(f"| {name} | {report.get(name, {})} |")

    compatibility_lines = ["| Dimension | Count | Average |", "| --- | ---: | ---: |"]
    for name, row in report.get("compatibility_dimension_summary", {}).items():
        compatibility_lines.append(f"| {name} | {row['count']} | {row['average']:.2f} |")

    warnings = report.get("warnings", [])
    warning_lines = "\n".join(f"- {warning}" for warning in warnings) if warnings else "- none"
    return "\n".join(
        [
            "# Generic Evidence Dataset Quality Report",
            "",
            "## Summary",
            "",
            f"- Events: {report['n_events']}",
            f"- Claims: {report['n_claims']}",
            f"- Evidence spans: {report['n_evidence_spans']}",
            f"- Evidence coverage: {report['evidence_coverage_rate']:.2%}",
            f"- Review coverage: {report['review_coverage_rate']:.2%}",
            "",
            "## Review Yield",
            "",
            f"- Human reviewed claims: {report['n_human_reviewed_claims']}",
            f"- Machine high-confidence claims: {report['n_machine_high_confidence_claims']}",
            f"- Rejected claims: {report['n_rejected_claims']}",
            f"- Needs review claims: {report['n_needs_review_claims']}",
            f"- Reviewed claim yield rate: {report['reviewed_claim_yield_rate']:.2%}",
            f"- Median review time {_TIME_UNIT}: {median_text}",
            f"- Average review time {_TIME_UNIT}: {average_text}",
            "",
            "## Field Precision",
            "",
            "\n".join(precision_lines),
            "",
            "## Source/Role Breakdown",
            "",
            "\n".join(role_lines),
            "",
            "## Compatibility Summary",
            "",
            "\n".join(compatibility_lines),
            "",
            "## Warnings",
            "",
            warning_lines,
            "",
        ]
    )


def build_generic_quality_report(
    *,
    events: pd.DataFrame | list[dict] | None = None,
    claims: pd.DataFrame | list[dict],
    evidence_spans: pd.DataFrame | list[dict],
    review_queue: pd.DataFrame | list[dict] | None = None,
    compatibility_reports: list[CompatibilityReport | dict] | None = None,
    out_json: str | Path | None = None,
    out_md: str | Path | None = None,
) -> dict:
    event_frame = _load_frame(events)
    claim_frame = _merge_review_queue(_load_frame(claims), _load_frame(review_queue))
    evidence_frame = _load_frame(evidence_spans)
    statuses = _string_series(claim_frame, "review_status").str.lower()

    n_claims = int(len(claim_frame))
    evidence_present = _evidence_present(claim_frame, evidence_frame)
    n_missing = int((~evidence_present).sum()) if len(evidence_present) else 0
    n_human = int(statuses.isin(HUMAN_REVIEW_STATUSES).sum())
    n_machine = int(statuses.isin(MACHINE_HIGH_CONFIDENCE_STATUSES).sum())
    n_rejected = int(statuses.isin(REJECTED_STATUSES).sum())
    n_needs = int(statuses.isin(NEEDS_REVIEW_STATUSES).sum())
    n_reviewed = n_human + n_machine
    yield_denominator = n_human + n_rejected
    dimension_summary, readiness_summary = _compatibility_summary(compatibility_reports)
    time_stats = _time_stats(claim_frame)

    warnings: list[str] = []
    if n_missing:
        warnings.append("missing_evidence")
    if n_claims and n_needs / n_claims > 0.5:
        warnings.append("high_needs_review_rate")
    if n_claims and n_human / n_claims < 0.5:
        warnings.append("low_human_review_coverage")

    report = {
        "n_events": int(len(event_frame)),
        "n_claims": n_claims,
        "n_evidence_spans": int(len(evidence_frame)),
        "n_reviewed_claims": n_reviewed,
        "n_human_reviewed_claims": n_human,
        "n_machine_high_confidence_claims": n_machine,
        "n_rejected_claims": n_rejected,
        "n_needs_review_claims": n_needs,
        "n_missing_evidence_claims": n_missing,
        "evidence_coverage_rate": float((n_claims - n_missing) / n_claims) if n_claims else 0.0,
        "review_coverage_rate": float(n_reviewed / n_claims) if n_claims else 0.0,
        "human_review_coverage_rate": float(n_human / n_claims) if n_claims else 0.0,
        "machine_high_confidence_rate": float(n_machine / n_claims) if n_claims else 0.0,
        "needs_review_rate": float(n_needs / n_claims) if n_claims else 0.0,
        "reviewed_claim_yield_rate": float(n_human / yield_denominator) if yield_denominator else 0.0,
        _MEDIAN_TIME_KEY: time_stats[_MEDIAN_TIME_KEY],
        _AVERAGE_TIME_KEY: time_stats[_AVERAGE_TIME_KEY],
        "field_coverage_by_field_name": _field_coverage(claim_frame, int(len(event_frame))),
        "field_precision_by_field_name": _field_precision(claim_frame),
        "issue_flag_counts": _split_counts(claim_frame, "issue_flags"),
        "review_action_counts": _value_counts(claim_frame, "review_action"),
        "parser_failure_reason_counts": _value_counts(claim_frame, "parser_failure_reason"),
        "claim_kind_counts": _value_counts(claim_frame, "claim_kind"),
        "claim_truth_status_counts": _value_counts(claim_frame, "claim_truth_status"),
        "source_authority_level_counts": _value_counts(claim_frame, "source_authority_level"),
        "source_role_counts": _value_counts(claim_frame, "source_role"),
        "source_system_counts": _value_counts(claim_frame, "source_system"),
        "compatibility_dimension_summary": dimension_summary,
        "readiness_summary": readiness_summary,
        "warnings": warnings,
    }
    report = json_friendly(report)

    if out_json is not None:
        path = Path(out_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if out_md is not None:
        path = Path(out_md)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_markdown(report), encoding="utf-8")
    return report
