from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .ids import json_friendly


MISSING_CLAIM_AUDIT_COLUMNS = [
    "source_doc_id",
    "event_id",
    "event_candidate_id",
    "expected_field",
    "expected_value",
    "evidence_text",
    "review_status",
    "missed_reason",
    "reviewer_notes",
]

ACCEPTED_EXTRACTED_STATUSES = {"reviewed", "approved", "human_reviewed", "machine_high_confidence", "auto_reviewed"}
IGNORED_AUDIT_STATUSES = {"rejected", "not_applicable", "not_expected", "ignore", "ignored", "false_positive"}


def _frame(data: pd.DataFrame | list[dict[str, Any]] | str | Path | None) -> pd.DataFrame:
    if data is None:
        return pd.DataFrame()
    if isinstance(data, pd.DataFrame):
        return data.copy()
    if isinstance(data, (str, Path)):
        return pd.read_csv(data).fillna("")
    return pd.DataFrame(data).fillna("")


def _clean(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _split_fields(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(part).strip() for part in value if str(part).strip()]


def write_missing_claim_audit_template(
    out_path: str | Path,
    *,
    events: pd.DataFrame | list[dict[str, Any]] | str | Path | None = None,
    expected_fields: str | list[str] | tuple[str, ...] | None = None,
) -> pd.DataFrame:
    event_frame = _frame(events)
    fields = _split_fields(expected_fields)
    rows: list[dict[str, Any]] = []
    if not event_frame.empty and fields:
        for _, event in event_frame.iterrows():
            for field in fields:
                rows.append(
                    {
                        "source_doc_id": _clean(event.get("source_doc_id")),
                        "event_id": _clean(event.get("event_id")),
                        "event_candidate_id": _clean(event.get("event_candidate_id")),
                        "expected_field": field,
                        "expected_value": "",
                        "evidence_text": "",
                        "review_status": "needs_review",
                        "missed_reason": "",
                        "reviewer_notes": "",
                    }
                )
    else:
        rows.append({column: "" for column in MISSING_CLAIM_AUDIT_COLUMNS})

    frame = pd.DataFrame(rows, columns=MISSING_CLAIM_AUDIT_COLUMNS)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return frame


def _merge_review_queue(claims: pd.DataFrame, review_queue: pd.DataFrame | None) -> pd.DataFrame:
    if claims.empty or review_queue is None or review_queue.empty or "claim_id" not in claims.columns or "claim_id" not in review_queue.columns:
        return claims
    merged = claims.copy()
    override_cols = [
        "review_status",
        "label_quality",
        "review_action",
        "issue_flags",
        "parser_failure_reason",
        "reviewer_notes",
    ]
    indexed_queue = review_queue.set_index("claim_id")
    for col in override_cols:
        if col not in indexed_queue.columns:
            continue
        if col not in merged.columns:
            merged[col] = ""
        merged[col] = merged[col].astype(object)
        for idx, claim_id in merged["claim_id"].items():
            if claim_id not in indexed_queue.index:
                continue
            value = indexed_queue.at[claim_id, col]
            if isinstance(value, pd.Series):
                value = value.iloc[0]
            value_text = _clean(value)
            if value_text:
                merged.at[idx, col] = value_text
    return merged


def _accepted_extracted_counts(claims: pd.DataFrame) -> dict[str, int]:
    if claims.empty or "field_name" not in claims.columns:
        return {}
    statuses = claims.get("review_status", pd.Series([""] * len(claims), index=claims.index)).map(lambda value: _clean(value).lower())
    accepted = claims[statuses.isin(ACCEPTED_EXTRACTED_STATUSES)]
    if accepted.empty:
        return {}
    return {str(field): int(count) for field, count in accepted.groupby("field_name").size().items()}


def _expected_missing_counts(audit: pd.DataFrame) -> dict[str, int]:
    if audit.empty or "expected_field" not in audit.columns:
        return {}
    frame = audit.copy()
    frame["expected_field"] = frame["expected_field"].map(_clean)
    frame = frame[frame["expected_field"] != ""]
    if frame.empty:
        return {}
    statuses = frame.get("review_status", pd.Series([""] * len(frame), index=frame.index)).map(lambda value: _clean(value).lower())
    frame = frame[~statuses.isin(IGNORED_AUDIT_STATUSES)]
    if frame.empty:
        return {}
    return {str(field): int(count) for field, count in frame.groupby("expected_field").size().items()}


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Missing Claim Recall Report",
        "",
        "## Summary",
        "",
        f"- Extracted accepted claims: {report['total_extracted_accepted_claims']}",
        f"- Expected missing claims: {report['total_expected_missing_claims']}",
        f"- Overall estimated recall: {report['overall_estimated_recall']:.2%}"
        if report["overall_estimated_recall"] is not None
        else "- Overall estimated recall: n/a",
        "",
        "## Field Recall",
        "",
        "| Field | Extracted Accepted | Expected Missing | Estimated Recall |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in report["field_recall"]:
        recall = "" if row["estimated_recall"] is None else f"{row['estimated_recall']:.2%}"
        lines.append(
            f"| {row['field_name']} | {row['extracted_accepted_count']} | {row['expected_missing_count']} | {recall} |"
        )
    if not report["field_recall"]:
        lines.append("| n/a | 0 | 0 |  |")
    lines.append("")
    return "\n".join(lines)


def build_missing_claim_recall_report(
    *,
    claims: pd.DataFrame | list[dict[str, Any]] | str | Path,
    missing_claim_audit: pd.DataFrame | list[dict[str, Any]] | str | Path,
    review_queue: pd.DataFrame | list[dict[str, Any]] | str | Path | None = None,
    out_json: str | Path | None = None,
    out_md: str | Path | None = None,
) -> dict[str, Any]:
    claim_frame = _merge_review_queue(_frame(claims), _frame(review_queue) if review_queue is not None else None)
    audit_frame = _frame(missing_claim_audit)
    accepted_counts = _accepted_extracted_counts(claim_frame)
    missing_counts = _expected_missing_counts(audit_frame)
    fields = sorted(set(accepted_counts) | set(missing_counts))

    field_recall = []
    for field in fields:
        extracted_count = accepted_counts.get(field, 0)
        missing_count = missing_counts.get(field, 0)
        denom = extracted_count + missing_count
        field_recall.append(
            {
                "field_name": field,
                "extracted_accepted_count": extracted_count,
                "expected_missing_count": missing_count,
                "estimated_recall": (extracted_count / denom) if denom else None,
            }
        )

    total_extracted = int(sum(accepted_counts.values()))
    total_missing = int(sum(missing_counts.values()))
    total_denom = total_extracted + total_missing
    report = {
        "total_extracted_accepted_claims": total_extracted,
        "total_expected_missing_claims": total_missing,
        "overall_estimated_recall": (total_extracted / total_denom) if total_denom else None,
        "field_recall": field_recall,
    }
    report = json_friendly(report)

    if out_json:
        path = Path(out_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        import json

        path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if out_md:
        path = Path(out_md)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_markdown_report(report), encoding="utf-8")
    return report
