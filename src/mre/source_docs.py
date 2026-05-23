from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from .paths import ensure_parent

SOURCE_DOC_COLUMNS = [
    "source_doc_id",
    "ticker",
    "event_id",
    "event_time",
    "event_type",
    "event_subtype",
    "release_session",
    "source_type",
    "source_url",
    "title",
    "path",
    "text",
    "fiscal_period_end",
    "sector_benchmark",
    "notes",
]

REQUIRED_SOURCE_DOC_COLUMNS = ["source_doc_id", "ticker", "event_time"]
VALID_RELEASE_SESSIONS = {"before_open", "intraday", "after_close", "unknown"}


@dataclass(frozen=True)
class SourceDocument:
    source_doc_id: str
    ticker: str
    event_id: str
    event_time: pd.Timestamp
    event_type: str
    event_subtype: str
    release_session: str
    source_type: str
    source_url: str
    title: str
    text: str
    path: str = ""
    fiscal_period_end: str = ""
    sector_benchmark: str = ""
    notes: str = ""


def _norm(value: object, default: str = "") -> str:
    text = str(value if value is not None else "").strip()
    if text.lower() in {"nan", "none", "null"}:
        return default
    return text or default


def _norm_lower(value: object, default: str = "unknown") -> str:
    return _norm(value, default=default).lower().strip() or default


def _normalize_ts(ts: object) -> pd.Timestamp:
    out = pd.to_datetime(ts, errors="coerce")
    if pd.isna(out):
        raise ValueError(f"Could not parse event_time: {ts!r}")
    out = pd.Timestamp(out)
    if out.tzinfo is not None:
        try:
            out = out.tz_convert(None)
        except TypeError:
            out = out.tz_localize(None)
    return out


def make_source_docs_template(out_path: str | Path, rows: Iterable[dict] | None = None) -> pd.DataFrame:
    """Write a CSV manifest template for raw source documents.

    Each row can provide either inline `text` or a filesystem `path`. Relative
    paths are resolved relative to the manifest file's directory.
    """
    df = pd.DataFrame(list(rows or []))
    for col in SOURCE_DOC_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[SOURCE_DOC_COLUMNS + [c for c in df.columns if c not in SOURCE_DOC_COLUMNS]]
    p = ensure_parent(out_path)
    df.to_csv(p, index=False)
    return df


def _read_text_from_path(path_value: object, manifest_dir: Path) -> str:
    rel = _norm(path_value)
    if not rel:
        return ""
    path = Path(rel)
    if not path.is_absolute():
        path = manifest_dir / path
    if not path.exists():
        raise FileNotFoundError(f"Source document path does not exist: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


def load_source_documents(manifest_path: str | Path) -> list[SourceDocument]:
    manifest_path = Path(manifest_path)
    df = pd.read_csv(manifest_path)
    for col in SOURCE_DOC_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    missing = [c for c in REQUIRED_SOURCE_DOC_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required source document columns: {missing}")
    docs: list[SourceDocument] = []
    seen: set[str] = set()
    for i, row in df.iterrows():
        doc_id = _norm(row.get("source_doc_id"), default=f"doc_{i+1:04d}")
        if doc_id in seen:
            raise ValueError(f"Duplicate source_doc_id: {doc_id}")
        seen.add(doc_id)
        ticker = _norm(row.get("ticker")).upper()
        if not ticker:
            raise ValueError(f"Missing ticker for source_doc_id={doc_id}")
        inline_text = _norm(row.get("text"))
        file_text = _read_text_from_path(row.get("path"), manifest_path.parent)
        text = inline_text or file_text
        if not text:
            raise ValueError(f"source_doc_id={doc_id} has neither inline text nor readable path")
        event_time = _normalize_ts(row.get("event_time"))
        event_id = _norm(row.get("event_id")) or f"{ticker}_{event_time.strftime('%Y%m%d_%H%M')}_{doc_id}"
        release_session = _norm_lower(row.get("release_session"), default="unknown")
        if release_session not in VALID_RELEASE_SESSIONS:
            raise ValueError(f"Invalid release_session for source_doc_id={doc_id}: {release_session}")
        docs.append(
            SourceDocument(
                source_doc_id=doc_id,
                ticker=ticker,
                event_id=event_id,
                event_time=event_time,
                event_type=_norm_lower(row.get("event_type"), default="earnings"),
                event_subtype=_norm_lower(row.get("event_subtype"), default="document_extracted"),
                release_session=release_session,
                source_type=_norm_lower(row.get("source_type"), default="source_document"),
                source_url=_norm(row.get("source_url")),
                title=_norm(row.get("title"), default=f"{ticker} source document"),
                text=text,
                path=_norm(row.get("path")),
                fiscal_period_end=_norm(row.get("fiscal_period_end")),
                sector_benchmark=_norm(row.get("sector_benchmark")).upper(),
                notes=_norm(row.get("notes")),
            )
        )
    return docs


def source_docs_to_frame(docs: Iterable[SourceDocument]) -> pd.DataFrame:
    rows = []
    for doc in docs:
        rows.append(
            {
                "source_doc_id": doc.source_doc_id,
                "ticker": doc.ticker,
                "event_id": doc.event_id,
                "event_time": doc.event_time.isoformat(),
                "event_type": doc.event_type,
                "event_subtype": doc.event_subtype,
                "release_session": doc.release_session,
                "source_type": doc.source_type,
                "source_url": doc.source_url,
                "title": doc.title,
                "path": doc.path,
                "fiscal_period_end": doc.fiscal_period_end,
                "sector_benchmark": doc.sector_benchmark,
                "notes": doc.notes,
                "text_chars": len(doc.text),
            }
        )
    return pd.DataFrame(rows)
