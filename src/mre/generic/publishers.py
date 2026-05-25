from __future__ import annotations

from html import escape
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .ids import json_friendly

HUMAN_REVIEW_STATUSES = {"reviewed", "approved", "human_reviewed"}
MACHINE_HIGH_CONFIDENCE_STATUSES = {"machine_high_confidence", "auto_reviewed"}
REJECTED_STATUSES = {"rejected"}
NEEDS_REVIEW_STATUSES = {"needs_review", "missing_evidence", ""}


def _frame(value: pd.DataFrame | list[dict] | None) -> pd.DataFrame:
    if value is None:
        return pd.DataFrame()
    if isinstance(value, pd.DataFrame):
        return value.copy()
    return pd.DataFrame(list(value))


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [json_friendly(row) for row in df.to_dict(orient="records")]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_friendly(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def merge_review_queue(claims, review_queue) -> pd.DataFrame:
    claim_frame = _frame(claims)
    review_frame = _frame(review_queue)
    if review_frame.empty or claim_frame.empty or "claim_id" not in claim_frame.columns or "claim_id" not in review_frame.columns:
        return claim_frame
    merged = claim_frame.merge(review_frame, on="claim_id", how="left", suffixes=("", "_review"))
    for col in ("review_status", "label_quality", "reviewer_notes", "review_action", "issue_flags"):
        review_col = f"{col}_review"
        if review_col not in merged.columns:
            continue
        values = merged[review_col]
        mask = values.notna() & (values.astype(str).str.strip() != "")
        if col not in merged.columns:
            merged[col] = ""
        merged.loc[mask, col] = values[mask]
        merged = merged.drop(columns=[review_col])
    return merged


def evidence_highlight_html(source_text, start_char, end_char, *, window=180) -> str:
    text = "" if source_text is None else str(source_text)
    try:
        start = int(start_char)
        end = int(end_char)
    except (TypeError, ValueError):
        return ""
    if start < 0 or end <= start or end > len(text):
        return ""
    left = max(0, start - int(window))
    right = min(len(text), end + int(window))
    prefix = escape(text[left:start])
    marked = escape(text[start:end])
    suffix = escape(text[end:right])
    return f"{'...' if left else ''}{prefix}<mark>{marked}</mark>{suffix}{'...' if right < len(text) else ''}"


def _status_counts(claims: pd.DataFrame) -> dict[str, int]:
    statuses = claims.get("review_status", pd.Series("", index=claims.index)).fillna("").astype(str).str.lower()
    return {
        "human_reviewed": int(statuses.isin(HUMAN_REVIEW_STATUSES).sum()),
        "machine_high_confidence": int(statuses.isin(MACHINE_HIGH_CONFIDENCE_STATUSES).sum()),
        "rejected": int(statuses.isin(REJECTED_STATUSES).sum()),
        "needs_review": int(statuses.isin(NEEDS_REVIEW_STATUSES).sum()),
    }


def _event_id(row: pd.Series) -> str:
    for col in ("event_id", "event_candidate_id"):
        if col in row and str(row.get(col, "")).strip():
            return str(row[col])
    return "unassigned"


def _claim_table_html(claims: pd.DataFrame, evidence: pd.DataFrame, source_texts: dict[str, str] | None) -> str:
    evidence_by_id = {str(row["evidence_span_id"]): row for _, row in evidence.iterrows()} if "evidence_span_id" in evidence.columns else {}
    rows = []
    for _, claim in claims.iterrows():
        span = evidence_by_id.get(str(claim.get("evidence_span_id", "")))
        snippet = ""
        if span is not None:
            source_text = (source_texts or {}).get(str(span.get("source_doc_id", "")))
            snippet = evidence_highlight_html(source_text, span.get("start_char", 0), span.get("end_char", 0)) if source_text else ""
            if not snippet:
                snippet = escape(str(span.get("evidence_text", "")))
        rows.append(
            "<tr>"
            f"<td><code>{escape(str(claim.get('field_name', '')))}</code></td>"
            f"<td>{escape(str(claim.get('value', '')))}</td>"
            f"<td>{escape(str(claim.get('confidence', '')))}</td>"
            f"<td>{escape(str(claim.get('review_status', '')))}</td>"
            f"<td>{escape(str(claim.get('label_quality', '')))}</td>"
            f"<td>{escape(str(claim.get('claim_kind', '')))}</td>"
            f"<td>{escape(str(claim.get('claim_truth_status', '')))}</td>"
            f"<td>{escape(str(claim.get('source_role', '')))}</td>"
            f"<td>{escape(str(claim.get('source_authority_level', '')))}</td>"
            f"<td>{escape(str(claim.get('method', '')))}</td>"
            f"<td>{snippet}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Field</th><th>Value</th><th>Confidence</th><th>Review</th>"
        "<th>Label Quality</th><th>Kind</th><th>Truth Status</th><th>Role</th><th>Authority</th><th>Method</th><th>Evidence</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def build_generic_static_site(
    *,
    events,
    claims,
    evidence_spans,
    out_dir,
    review_queue=None,
    source_texts: dict[str, str] | None = None,
    title="Evidence Event Dataset",
) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    event_frame = _frame(events)
    claim_frame = merge_review_queue(claims, review_queue)
    evidence_frame = _frame(evidence_spans)
    counts = _status_counts(claim_frame)

    event_ids = list(event_frame["event_id"].astype(str)) if "event_id" in event_frame.columns else sorted({_event_id(row) for _, row in claim_frame.iterrows()})
    event_dir = out / "event"
    event_dir.mkdir(exist_ok=True)
    links = []
    for event_id in event_ids:
        event_claims = claim_frame[claim_frame.apply(_event_id, axis=1) == event_id] if not claim_frame.empty else pd.DataFrame()
        event_rows = event_frame[event_frame["event_id"].astype(str) == event_id] if "event_id" in event_frame.columns else pd.DataFrame()
        event_payload = event_rows.iloc[0].to_dict() if not event_rows.empty else {"event_id": event_id}
        table = _claim_table_html(event_claims, evidence_frame, source_texts)
        page = "\n".join(
            [
                "<!doctype html><meta charset='utf-8'>",
                f"<title>{escape(str(title))} - {escape(event_id)}</title>",
                f"<h1>{escape(event_id)}</h1>",
                f"<p>Family: {escape(str(event_payload.get('event_family', '')))} Type: {escape(str(event_payload.get('event_type', '')))} Status: {escape(str(event_payload.get('status', '')))}</p>",
                table,
            ]
        )
        page_path = event_dir / f"{event_id}.html"
        page_path.write_text(page, encoding="utf-8")
        links.append(f"<li><a href='event/{escape(event_id)}.html'>{escape(event_id)}</a></li>")

    index = "\n".join(
        [
            "<!doctype html><meta charset='utf-8'>",
            f"<title>{escape(str(title))}</title>",
            f"<h1>{escape(str(title))}</h1>",
            f"<p>Events: {len(event_ids)} Claims: {len(claim_frame)} Human reviewed: {counts['human_reviewed']} Machine high-confidence: {counts['machine_high_confidence']} Rejected: {counts['rejected']} Needs review: {counts['needs_review']}</p>",
            "<ul>",
            *links,
            "</ul>",
        ]
    )
    (out / "index.html").write_text(index, encoding="utf-8")
    (out / "events.html").write_text(index, encoding="utf-8")
    api_dir = out / "api"
    _write_json(api_dir / "events.json", _records(event_frame))
    _write_json(api_dir / "claims.json", _records(claim_frame))
    _write_json(api_dir / "evidence_spans.json", _records(evidence_frame))
    return {
        "index": str(out / "index.html"),
        "events": str(out / "events.html"),
        "event_pages": len(event_ids),
        "events_json": str(api_dir / "events.json"),
        "claims_json": str(api_dir / "claims.json"),
        "evidence_spans_json": str(api_dir / "evidence_spans.json"),
    }


def export_generic_api(
    *,
    events,
    claims,
    evidence_spans,
    out_dir,
    review_queue=None,
    include_evidence=True,
) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    event_frame = _frame(events)
    claim_frame = merge_review_queue(claims, review_queue)
    evidence_frame = _frame(evidence_spans)
    evidence_records = _records(evidence_frame) if include_evidence else []
    claims_by_event: dict[str, list[dict]] = {}
    for _, claim in claim_frame.iterrows():
        claims_by_event.setdefault(_event_id(claim), []).append(json_friendly(claim.to_dict()))
    event_records = _records(event_frame)
    for event in event_records:
        event["claims"] = claims_by_event.get(str(event.get("event_id", "")), [])
    compact = [{k: row.get(k) for k in ("event_id", "event_family", "event_type", "status") if k in row} for row in event_records]
    fields_summary = claim_frame["field_name"].value_counts().sort_index().to_dict() if "field_name" in claim_frame.columns else {}
    sources_summary = {
        "source_system": claim_frame["source_system"].value_counts().sort_index().to_dict() if "source_system" in claim_frame.columns else {},
        "source_role": claim_frame["source_role"].value_counts().sort_index().to_dict() if "source_role" in claim_frame.columns else {},
    }
    outputs = {
        "events": out / "events.json",
        "claims": out / "claims.json",
        "evidence_spans": out / "evidence_spans.json",
        "events_compact": out / "events_compact.json",
        "fields_summary": out / "fields_summary.json",
        "sources_summary": out / "sources_summary.json",
    }
    _write_json(outputs["events"], event_records)
    _write_json(outputs["claims"], _records(claim_frame))
    _write_json(outputs["evidence_spans"], evidence_records)
    _write_json(outputs["events_compact"], compact)
    _write_json(outputs["fields_summary"], fields_summary)
    _write_json(outputs["sources_summary"], sources_summary)
    return {key: str(value) for key, value in outputs.items()}


def build_generic_digest(
    *,
    events,
    claims,
    evidence_spans,
    review_queue=None,
    title="Evidence Event Digest",
    out_path=None,
    max_items=20,
) -> str:
    claim_frame = merge_review_queue(claims, review_queue)
    evidence_frame = _frame(evidence_spans)
    counts = _status_counts(claim_frame)
    evidence_by_id = {str(row["evidence_span_id"]): row for _, row in evidence_frame.iterrows()} if "evidence_span_id" in evidence_frame.columns else {}
    accepted_statuses = HUMAN_REVIEW_STATUSES | MACHINE_HIGH_CONFIDENCE_STATUSES
    rows = []
    for _, claim in claim_frame.iterrows():
        status = str(claim.get("review_status", "")).lower()
        if status not in accepted_statuses:
            continue
        span = evidence_by_id.get(str(claim.get("evidence_span_id", "")))
        snippet = "" if span is None else str(span.get("evidence_text", ""))
        rows.append(f"- `{claim.get('field_name', '')}` = {claim.get('value', '')} ({status})\n  Evidence: {snippet}")
        if len(rows) >= max_items:
            break
    digest = "\n".join(
        [
            f"# {title}",
            "",
            f"- Events: {len(_frame(events))}",
            f"- Claims: {len(claim_frame)}",
            f"- Human reviewed: {counts['human_reviewed']}",
            f"- Machine high-confidence: {counts['machine_high_confidence']}",
            f"- Rejected: {counts['rejected']}",
            f"- Needs review: {counts['needs_review']}",
            "",
            "## Notable Claims",
            "",
            "\n".join(rows) if rows else "- none",
            "",
        ]
    )
    if out_path is not None:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(digest, encoding="utf-8")
    return digest
