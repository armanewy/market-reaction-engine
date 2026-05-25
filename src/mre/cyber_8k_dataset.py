from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .amendments import add_amendment_flags, build_amendment_chains
from .claim_review import make_claim_review_queue
from .cyber_8k_plugin import run_cyber_8k_plugin_manifest
from .paths import ensure_dir, ensure_parent
from .source_docs import SourceDocument, load_source_documents
from .timestamp_readiness import classify_release_session_readiness_frame


BOOLEAN_CYBER_FIELDS = [
    "ransomware_mentioned",
    "customer_data_exposure_mentioned",
    "operational_disruption_mentioned",
    "third_party_vendor_mentioned",
    "no_material_impact_language",
    "impact_unknown_or_not_determined",
    "reasonably_likely_material_impact_language",
]


def _load_frame(value: str | Path | pd.DataFrame | None) -> pd.DataFrame | None:
    if value is None:
        return None
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


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _notes(doc: SourceDocument) -> dict[str, Any]:
    try:
        parsed = json.loads(doc.notes) if doc.notes else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _event_rows_from_documents(docs: list[SourceDocument], claims: pd.DataFrame, review_queue: pd.DataFrame, run_manifest_path: str | Path | None) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    by_event = {event_id: group.copy() for event_id, group in claims.groupby("event_id")} if not claims.empty and "event_id" in claims.columns else {}
    review_by_event = {event_id: group.copy() for event_id, group in review_queue.groupby("event_id")} if not review_queue.empty and "event_id" in review_queue.columns else {}
    seen: set[str] = set()
    for doc in docs:
        if doc.event_id in seen:
            continue
        seen.add(doc.event_id)
        notes = _notes(doc)
        event_claims = by_event.get(doc.event_id, pd.DataFrame())
        event_review = review_by_event.get(doc.event_id, pd.DataFrame())
        row: dict[str, Any] = {
            "event_id": doc.event_id,
            "ticker": doc.ticker,
            "cik": _norm(notes.get("cik")),
            "company_name": _norm(notes.get("company_name")),
            "event_time": doc.event_time.isoformat(),
            "event_type": "cybersecurity",
            "event_subtype": doc.event_subtype or "sec_8_k_item_1_05",
            "event_family": "cybersecurity_material_incidents_8k",
            "release_session": doc.release_session,
            "summary": doc.title or f"{doc.ticker} cybersecurity disclosure",
            "source_doc_ids": doc.source_doc_id,
            "source_url": doc.source_url,
            "form": _norm(notes.get("form")),
            "accession": _norm(notes.get("accession")),
            "filing_date": _norm(notes.get("filing_date")),
            "accepted_at": _norm(notes.get("accepted_at")),
            "item_numbers": _norm(notes.get("item_numbers")),
            "run_manifest_path": str(run_manifest_path or ""),
        }
        for field in BOOLEAN_CYBER_FIELDS:
            field_claims = event_claims[event_claims["field_name"].astype(str) == field] if not event_claims.empty else pd.DataFrame()
            row[field] = bool(not field_claims.empty and field_claims["value"].map(_bool_value).any())
        row["n_claims"] = int(len(event_claims))
        row["n_reviewed_claims"] = int(event_review.get("review_status", pd.Series(dtype=str)).fillna("").astype(str).str.lower().isin({"reviewed", "approved"}).sum()) if not event_review.empty else 0
        row["n_missing_evidence_claims"] = int(event_review.get("issue_flags", pd.Series(dtype=str)).fillna("").astype(str).str.contains("missing_evidence").sum()) if not event_review.empty else 0
        if row["n_claims"] and row["n_reviewed_claims"] == row["n_claims"]:
            row["event_review_status"] = "reviewed"
        elif row["n_claims"]:
            row["event_review_status"] = "needs_review"
        else:
            row["event_review_status"] = "no_claims"
        rows.append(row)
    frame = pd.DataFrame(rows)
    return classify_release_session_readiness_frame(frame) if not frame.empty else frame


def _write_json(path: Path, obj: dict) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def build_cyber_8k_dataset(
    documents_manifest,
    *,
    claims_csv=None,
    evidence_spans_csv=None,
    review_queue_csv=None,
    filings_csv=None,
    out_dir,
    run_manifest_path=None,
    auto_accept_min_confidence=None,
) -> dict:
    out = ensure_dir(out_dir)
    docs = load_source_documents(documents_manifest)

    claims = _load_frame(claims_csv)
    evidence = _load_frame(evidence_spans_csv)
    parse_diagnostics: dict[str, Any] = {}
    if claims is None or evidence is None:
        claims, evidence, parse_diagnostics = run_cyber_8k_plugin_manifest(documents_manifest)

    review_queue = _load_frame(review_queue_csv)
    review_diagnostics: dict[str, Any] = {}
    if review_queue is None:
        review_queue, review_diagnostics = make_claim_review_queue(claims, evidence, auto_accept_min_confidence=auto_accept_min_confidence)

    events = _event_rows_from_documents(docs, claims, review_queue, run_manifest_path)

    paths = {
        "events": out / "cyber_events.csv",
        "claims": out / "cyber_claims.csv",
        "evidence_spans": out / "cyber_evidence_spans.csv",
        "review_queue": out / "cyber_claim_review_queue.csv",
        "summary": out / "cyber_summary.json",
    }
    events.to_csv(paths["events"], index=False)
    claims.to_csv(paths["claims"], index=False)
    evidence.to_csv(paths["evidence_spans"], index=False)
    review_queue.to_csv(paths["review_queue"], index=False)

    amendment_path = None
    if filings_csv is not None:
        chains = build_amendment_chains(filings_csv, events)
        amendment_path = out / "amendment_chains.csv"
        chains.to_csv(amendment_path, index=False)
        events = add_amendment_flags(events, chains)
        events.to_csv(paths["events"], index=False)

    summary = {
        "documents": int(len(docs)),
        "events": int(len(events)),
        "claims": int(len(claims)),
        "evidence_spans": int(len(evidence)),
        "review_queue_rows": int(len(review_queue)),
        "reviewed_claims": int(review_queue.get("review_status", pd.Series(dtype=str)).fillna("").astype(str).str.lower().isin({"reviewed", "approved"}).sum()) if not review_queue.empty else 0,
        "missing_evidence_claims": int(review_queue.get("issue_flags", pd.Series(dtype=str)).fillna("").astype(str).str.contains("missing_evidence").sum()) if not review_queue.empty else 0,
        "parse_diagnostics": parse_diagnostics,
        "review_diagnostics": review_diagnostics,
        "run_manifest_path": str(run_manifest_path or ""),
        "outputs": {key: str(value) for key, value in paths.items()},
    }
    if amendment_path is not None:
        summary["outputs"]["amendment_chains"] = str(amendment_path)
    _write_json(paths["summary"], summary)
    return summary
