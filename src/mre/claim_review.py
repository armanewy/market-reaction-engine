from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from .paths import ensure_parent


REVIEW_QUEUE_COLUMNS = [
    "claim_id",
    "event_id",
    "field_name",
    "value",
    "value_type",
    "confidence",
    "method",
    "source_doc_id",
    "evidence_span_id",
    "evidence_text",
    "evidence_present",
    "review_status",
    "label_quality",
    "reviewer_notes",
    "review_action",
    "issue_flags",
]


@dataclass
class ClaimReviewDiagnostics:
    claims_total: int = 0
    claims_with_evidence: int = 0
    claims_missing_evidence: int = 0
    auto_reviewed: int = 0
    needs_review: int = 0
    rejected: int = 0
    issue_counts: dict[str, int] = field(default_factory=dict)

    def add_issue(self, issue: str) -> None:
        self.issue_counts[issue] = self.issue_counts.get(issue, 0) + 1

    def to_dict(self) -> dict:
        return asdict(self)


def _load_frame(value: str | Path | pd.DataFrame) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    return pd.read_csv(value)


def _norm(value: object, default: str = "") -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return default
    return text or default


def make_claim_review_queue(
    claims_csv_or_df: str | Path | pd.DataFrame,
    evidence_spans_csv_or_df: str | Path | pd.DataFrame,
    out_path: str | Path | None = None,
    *,
    auto_accept_min_confidence: float | None = None,
    require_evidence: bool = True,
) -> tuple[pd.DataFrame, dict]:
    claims = _load_frame(claims_csv_or_df)
    evidence = _load_frame(evidence_spans_csv_or_df)

    for col in ["claim_id", "evidence_span_id", "source_doc_id"]:
        if col not in claims.columns:
            claims[col] = ""
        if col not in evidence.columns:
            evidence[col] = ""
    if "evidence_text" not in evidence.columns:
        evidence["evidence_text"] = ""

    evidence_keyed = evidence[["evidence_span_id", "source_doc_id", "claim_id", "evidence_text"]].copy()
    evidence_keyed = evidence_keyed.drop_duplicates(subset=["evidence_span_id", "source_doc_id", "claim_id"], keep="first")
    queue = claims.merge(
        evidence_keyed,
        on=["evidence_span_id", "source_doc_id", "claim_id"],
        how="left",
        suffixes=("", "_evidence"),
    )

    diagnostics = ClaimReviewDiagnostics(claims_total=int(len(queue)))
    rows: list[dict] = []
    preserved_statuses = {"reviewed", "approved", "rejected"}
    for _, row in queue.iterrows():
        evidence_text = _norm(row.get("evidence_text"))
        evidence_present = bool(evidence_text)
        issue_flags: list[str] = []
        if not evidence_present and require_evidence:
            issue_flags.append("missing_evidence")
            diagnostics.add_issue("missing_evidence")

        current_status = _norm(row.get("review_status"), default="needs_review").lower()
        confidence = float(row.get("confidence") or 0.0)
        if current_status in preserved_statuses:
            review_status = current_status
            label_quality = _norm(row.get("label_quality"), default="human_reviewed" if current_status == "reviewed" else "")
        elif issue_flags:
            review_status = "needs_review"
            label_quality = _norm(row.get("label_quality"))
        elif auto_accept_min_confidence is not None and confidence >= auto_accept_min_confidence and evidence_present:
            review_status = "reviewed"
            label_quality = "machine_high_confidence"
            diagnostics.auto_reviewed += 1
        else:
            review_status = "needs_review"
            label_quality = _norm(row.get("label_quality"))

        if evidence_present:
            diagnostics.claims_with_evidence += 1
        else:
            diagnostics.claims_missing_evidence += 1
        if review_status == "rejected":
            diagnostics.rejected += 1
        elif review_status == "needs_review":
            diagnostics.needs_review += 1

        rows.append(
            {
                "claim_id": _norm(row.get("claim_id")),
                "event_id": _norm(row.get("event_id")),
                "field_name": _norm(row.get("field_name")),
                "value": row.get("value", ""),
                "value_type": _norm(row.get("value_type"), default="string"),
                "confidence": confidence,
                "method": _norm(row.get("method")),
                "source_doc_id": _norm(row.get("source_doc_id")),
                "evidence_span_id": _norm(row.get("evidence_span_id")),
                "evidence_text": evidence_text,
                "evidence_present": evidence_present,
                "review_status": review_status,
                "label_quality": label_quality,
                "reviewer_notes": _norm(row.get("reviewer_notes")),
                "review_action": _norm(row.get("review_action")),
                "issue_flags": ";".join(issue_flags),
            }
        )

    out = pd.DataFrame(rows, columns=REVIEW_QUEUE_COLUMNS)
    if out_path is not None:
        p = ensure_parent(out_path)
        out.to_csv(p, index=False)
    return out, diagnostics.to_dict()
