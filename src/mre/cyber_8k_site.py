from __future__ import annotations

import html
import json
from pathlib import Path
import re
from typing import Any

import pandas as pd

from .paths import ensure_dir, ensure_parent


def _load_csv(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)


def _safe_filename(value: object, default: str = "item") -> str:
    text = str(value if value is not None else "").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")
    return text[:160] or default


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
    return value


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        rows.append({str(col): _clean_value(row.get(col)) for col in df.columns})
    return rows


def _write_json(path: Path, records: list[dict[str, Any]]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(records, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _e(value: object) -> str:
    cleaned = _clean_value(value)
    return html.escape("" if cleaned is None else str(cleaned))


def _first_clean_value(*values: object) -> Any:
    for value in values:
        cleaned = _clean_value(value)
        if cleaned is not None and str(cleaned).strip():
            return cleaned
    return None


def evidence_highlight_html(source_text: object, start_char: object, end_char: object, *, window: int = 180) -> str:
    text = _clean_value(source_text)
    if not text:
        return ""
    try:
        start = int(start_char)
        end = int(end_char)
    except (TypeError, ValueError):
        return ""
    source = str(text)
    if start < 0 or end <= start or start >= len(source):
        return ""
    end = min(end, len(source))
    left = max(0, start - window)
    right = min(len(source), end + window)
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(source) else ""
    return (
        _e(prefix + source[left:start])
        + "<mark>"
        + _e(source[start:end])
        + "</mark>"
        + _e(source[end:right] + suffix)
    )


def _claim_rows_for_event(claims: pd.DataFrame, evidence: pd.DataFrame, event_id: object) -> pd.DataFrame:
    if claims.empty:
        return pd.DataFrame()
    event_claims = claims[claims["event_id"].astype(str) == str(event_id)].copy()
    if event_claims.empty or evidence.empty:
        return event_claims
    evidence_cols = [
        c
        for c in [
            "evidence_span_id",
            "source_doc_id",
            "claim_id",
            "evidence_text",
            "start_char",
            "end_char",
            "source_text",
            "document_text",
            "text",
            "source_url",
        ]
        if c in evidence.columns
    ]
    if not {"evidence_span_id", "source_doc_id", "claim_id"}.issubset(evidence_cols):
        return event_claims
    return event_claims.merge(
        evidence[evidence_cols],
        on=["evidence_span_id", "source_doc_id", "claim_id"],
        how="left",
        suffixes=("", "_evidence"),
    )


def _page(title: str, body: str) -> str:
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{_e(title)}</title>",
            "<style>body{font-family:Arial,sans-serif;max-width:980px;margin:2rem auto;padding:0 1rem;line-height:1.45}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:.45rem;text-align:left;vertical-align:top}code{background:#f5f5f5;padding:.1rem .25rem}blockquote{border-left:3px solid #888;margin-left:0;padding-left:1rem;color:#333}</style>",
            "</head>",
            "<body>",
            body,
            "</body>",
            "</html>",
            "",
        ]
    )


def _event_detail_html(event: pd.Series, claims: pd.DataFrame) -> str:
    rows = []
    for _, claim in claims.iterrows():
        rows.append(
            "<tr>"
            f"<td><code>{_e(claim.get('field_name'))}</code></td>"
            f"<td>{_e(claim.get('value'))}</td>"
            f"<td>{_e(claim.get('confidence'))}</td>"
            f"<td>{_e(claim.get('review_status'))}</td>"
            f"<td>{_e(claim.get('method'))}</td>"
            "</tr>"
        )
    evidence_blocks = []
    for _, claim in claims.iterrows():
        evidence_text = _clean_value(claim.get("evidence_text"))
        source_text = _first_clean_value(claim.get("source_text"), claim.get("document_text"), claim.get("text"))
        highlighted = evidence_highlight_html(source_text, claim.get("start_char"), claim.get("end_char")) if source_text else ""
        if evidence_text:
            evidence_blocks.append(
                f"<h3>{_e(claim.get('field_name'))}</h3>"
                f"<blockquote>{highlighted or _e(evidence_text)}</blockquote>"
                f"<p><a href=\"{_e(claim.get('source_url'))}\">{_e(claim.get('source_url'))}</a></p>"
            )
    body = f"""
<p><a href="../index.html">Cyber 8-K Watch</a></p>
<h1>{_e(event.get("summary") or event.get("event_id"))}</h1>
<dl>
  <dt>Company</dt><dd>{_e(event.get("company_name") or event.get("ticker") or event.get("cik"))}</dd>
  <dt>Ticker / CIK</dt><dd>{_e(event.get("ticker"))} / {_e(event.get("cik"))}</dd>
  <dt>Form / Accession</dt><dd>{_e(event.get("form"))} / {_e(event.get("accession"))}</dd>
  <dt>Event Time</dt><dd>{_e(event.get("event_time"))}</dd>
  <dt>Release Session</dt><dd>{_e(event.get("release_session"))}</dd>
  <dt>Source</dt><dd><a href="{_e(event.get("source_url"))}">{_e(event.get("source_url"))}</a></dd>
</dl>
<h2>Structured Claims</h2>
<table><thead><tr><th>Field</th><th>Value</th><th>Confidence</th><th>Review</th><th>Method</th></tr></thead><tbody>
{''.join(rows)}
</tbody></table>
<h2>Evidence</h2>
{''.join(evidence_blocks) or '<p>No evidence spans supplied.</p>'}
"""
    return _page(str(event.get("event_id")), body)


def _events_index_html(events: pd.DataFrame) -> str:
    rows = []
    for _, event in events.iterrows():
        event_id = event.get("event_id")
        rows.append(
            "<tr>"
            f'<td><a href="event/{_safe_filename(event_id)}.html">{_e(event_id)}</a></td>'
            f"<td>{_e(event.get('ticker'))}</td>"
            f"<td>{_e(event.get('event_time'))}</td>"
            f"<td>{_e(event.get('summary'))}</td>"
            "</tr>"
        )
    return "<table><thead><tr><th>Event</th><th>Ticker</th><th>Time</th><th>Summary</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


def build_cyber_8k_static_site(
    events_csv,
    claims_csv,
    evidence_spans_csv,
    out_dir,
    *,
    title: str = "Cyber 8-K Watch",
) -> dict:
    events = _load_csv(events_csv)
    claims = _load_csv(claims_csv)
    evidence = _load_csv(evidence_spans_csv)
    out = ensure_dir(out_dir)
    ensure_dir(out / "api")
    ensure_dir(out / "event")
    ensure_dir(out / "company")

    _write_json(out / "api" / "events.json", _records(events))
    _write_json(out / "api" / "claims.json", _records(claims))
    _write_json(out / "api" / "evidence_spans.json", _records(evidence))

    companies = set()
    for _, event in events.iterrows():
        key = _clean_value(event.get("ticker")) or _clean_value(event.get("cik"))
        if key:
            companies.add(str(key))
        event_claims = _claim_rows_for_event(claims, evidence, event.get("event_id"))
        (out / "event" / f"{_safe_filename(event.get('event_id'))}.html").write_text(_event_detail_html(event, event_claims), encoding="utf-8")

    for company in sorted(companies):
        company_events = events[(events.get("ticker", pd.Series("", index=events.index)).astype(str) == company) | (events.get("cik", pd.Series("", index=events.index)).astype(str) == company)]
        body = f"<p><a href=\"../index.html\">Cyber 8-K Watch</a></p><h1>{_e(company)}</h1>{_events_index_html(company_events)}"
        (out / "company" / f"{_safe_filename(company)}.html").write_text(_page(company, body), encoding="utf-8")

    reviewed_claims = int(claims.get("review_status", pd.Series("", index=claims.index)).fillna("").astype(str).str.lower().isin({"reviewed", "approved"}).sum())
    unreviewed_claims = int(len(claims) - reviewed_claims)
    index_body = f"""
<h1>{_e(title)}</h1>
<ul>
  <li>Events: {len(events)}</li>
  <li>Companies: {len(companies)}</li>
  <li>Claims: {len(claims)}</li>
  <li>Reviewed claims: {reviewed_claims}</li>
  <li>Unreviewed claims: {unreviewed_claims}</li>
</ul>
{_events_index_html(events)}
"""
    (out / "index.html").write_text(_page(title, index_body), encoding="utf-8")
    (out / "events.html").write_text(_page(f"{title} Events", _events_index_html(events)), encoding="utf-8")

    return {
        "index": str(out / "index.html"),
        "events": str(out / "events.html"),
        "events_json": str(out / "api" / "events.json"),
        "claims_json": str(out / "api" / "claims.json"),
        "evidence_spans_json": str(out / "api" / "evidence_spans.json"),
        "event_pages": int(len(events)),
        "company_pages": int(len(companies)),
    }
