from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse

import pandas as pd
import requests

from .paths import ensure_parent
from .sec import SecClient, _release_session_from_acceptance
from .source_docs import SOURCE_DOC_COLUMNS, make_source_docs_template

HTML_EXTENSIONS = {".htm", ".html", ".xhtml", ".xml", ".txt"}
DEFAULT_SEC_EXHIBIT_PATTERN = r"(?i)(ex[-_]?99|exhibit[-_ ]?99|dex99|99[._-]?1|earnings|results|press[-_ ]?release)"
DEFAULT_USER_AGENT = "market-reaction-engine/0.6 contact@example.com"


@dataclass
class IngestionDiagnostics:
    rows_total: int = 0
    rows_written: int = 0
    rows_skipped: int = 0
    downloaded: int = 0
    local_files_read: int = 0
    inline_rows_read: int = 0
    text_chars_total: int = 0
    skipped_reasons: dict[str, int] = field(default_factory=dict)

    def add_skip(self, reason: str) -> None:
        self.rows_skipped += 1
        self.skipped_reasons[reason] = self.skipped_reasons.get(reason, 0) + 1

    def to_dict(self) -> dict:
        return asdict(self)


class _VisibleHTMLParser(HTMLParser):
    """Small standard-library HTML-to-text parser.

    This is intentionally dependency-free so the ingestion layer can run before
    users install heavier parsing libraries. It is good enough for SEC/IR HTML
    normalization, but not a substitute for a production document parser.
    """

    BLOCK_TAGS = {
        "address", "article", "aside", "blockquote", "br", "caption", "div", "dl", "dt", "dd", "figcaption",
        "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav",
        "ol", "p", "pre", "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
    }
    SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "math"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def _norm(value: object, default: str = "") -> str:
    text = str(value if value is not None else "").strip()
    if text.lower() in {"nan", "none", "null"}:
        return default
    return text or default


def _safe_id(text: object, default: str = "doc") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", _norm(text, default=default)).strip("_")
    return cleaned[:180] or default


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def collapse_text(text: str) -> str:
    """Collapse noisy whitespace while retaining paragraph-ish breaks."""
    text = html.unescape(str(text or "")).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\t\x0b\x0c ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_text(content: str | bytes) -> str:
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    parser = _VisibleHTMLParser()
    parser.feed(content)
    parser.close()
    return collapse_text(parser.text())


def normalize_document_text(content: str | bytes, *, content_type: str = "", source_name: str = "") -> str:
    """Normalize raw HTML/text into extraction-ready plain text."""
    raw = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content or "")
    low_type = content_type.lower()
    suffix = Path(urlparse(source_name).path).suffix.lower() if source_name else ""
    if "html" in low_type or suffix in {".htm", ".html", ".xhtml"} or re.search(r"<\s*html|<\s*body|<\s*table|<\s*p\b|<\s*div\b", raw, re.I):
        return html_to_text(raw)
    return collapse_text(raw)


def _relative_path(path: Path, base_dir: Path) -> str:
    """Return a manifest-safe path relative to the manifest directory."""
    try:
        return path.relative_to(base_dir).as_posix()
    except ValueError:
        return os.path.relpath(path, base_dir).replace(os.sep, "/")


def _write_text_file(path: Path, text: str, *, overwrite: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        return
    path.write_text(text, encoding="utf-8")


def _session(user_agent: str | None = None) -> requests.Session:
    sess = requests.Session()
    sess.headers.update({"User-Agent": user_agent or os.environ.get("MRE_USER_AGENT", DEFAULT_USER_AGENT)})
    return sess


def fetch_url_text(url: str, *, user_agent: str | None = None, timeout: float = 30.0) -> tuple[str, str]:
    """Fetch and normalize a URL. Supports HTTP(S) and file:// for tests/demos."""
    if str(url).startswith("file://"):
        parsed = urlparse(str(url))
        path = Path(unquote(parsed.path))
        content_type = "text/html" if path.suffix.lower() in {".htm", ".html", ".xhtml"} else "text/plain"
        return normalize_document_text(path.read_bytes(), content_type=content_type, source_name=str(path)), content_type
    sess = _session(user_agent)
    resp = sess.get(url, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(f"URL fetch failed {resp.status_code}: {url}\n{resp.text[:500]}")
    content_type = resp.headers.get("Content-Type", "")
    return normalize_document_text(resp.content, content_type=content_type, source_name=url), content_type


def make_ingestion_template(out_path: str | Path) -> pd.DataFrame:
    """Write a practical source-ingestion manifest template.

    Rows may provide `source_url`, `path`, or inline `text`. The ingestion command
    will normalize each document and write a text file for the extraction layer.
    """
    rows = [
        {
            "source_doc_id": "AAPL_2024Q1_press_release",
            "ticker": "AAPL",
            "event_id": "AAPL_2024Q1_EARNINGS",
            "event_time": "2024-02-01T16:30:00",
            "event_type": "earnings",
            "event_subtype": "earnings_release",
            "release_session": "after_close",
            "source_type": "company_press_release",
            "source_url": "https://example.com/company/q1-2024-results.html",
            "title": "Example company Q1 2024 results",
            "path": "",
            "text": "",
            "fiscal_period_end": "2023-12-30",
            "sector_benchmark": "XLK",
            "notes": "Replace with a real investor-relations URL, local path, or inline text.",
        }
    ]
    return make_source_docs_template(out_path, rows=rows)


def ingest_source_document_manifest(
    input_manifest: str | Path,
    out_manifest: str | Path,
    docs_dir: str | Path,
    *,
    user_agent: str | None = None,
    requests_per_second: float = 2.0,
    overwrite: bool = False,
    include_inline_text: bool = False,
    min_text_chars: int = 20,
) -> tuple[pd.DataFrame, IngestionDiagnostics]:
    """Download/normalize URL, local-path, or inline-text rows into source docs.

    The output manifest is compatible with `mre extract-facts`. Text is written
    to `docs_dir` so raw source ingestion stays auditable and reproducible.
    """
    input_manifest = Path(input_manifest)
    out_manifest = Path(out_manifest)
    docs_dir = Path(docs_dir)
    df = pd.read_csv(input_manifest)
    for col in SOURCE_DOC_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    diag = IngestionDiagnostics(rows_total=int(len(df)))
    out_rows: list[dict] = []
    sess = _session(user_agent)
    delay = 1.0 / max(float(requests_per_second), 0.1)

    for i, row in df.iterrows():
        source_url = _norm(row.get("source_url"))
        src_path_value = _norm(row.get("path"))
        inline_text = _norm(row.get("text"))
        source_name = source_url or src_path_value or f"row_{i+1}"
        doc_id = _norm(row.get("source_doc_id"))
        ticker = _norm(row.get("ticker")).upper()
        event_time = _norm(row.get("event_time"))
        if not doc_id:
            doc_id = _safe_id("_".join([ticker or "TICKER", event_time[:10] or f"row{i+1}", Path(urlparse(source_name).path).stem or "source"]))
        if not ticker:
            diag.add_skip("missing ticker")
            continue
        if not event_time:
            diag.add_skip("missing event_time")
            continue

        content_type = ""
        raw_text = ""
        try:
            if source_url:
                if source_url.startswith("file://"):
                    raw_text, content_type = fetch_url_text(source_url, user_agent=user_agent)
                else:
                    resp = sess.get(source_url, timeout=30)
                    if resp.status_code >= 400:
                        raise RuntimeError(f"URL fetch failed {resp.status_code}: {source_url}")
                    content_type = resp.headers.get("Content-Type", "")
                    raw_text = normalize_document_text(resp.content, content_type=content_type, source_name=source_url)
                    time.sleep(delay)
                diag.downloaded += 1
            elif src_path_value:
                src_path = Path(src_path_value)
                if not src_path.is_absolute():
                    src_path = input_manifest.parent / src_path
                raw_bytes = src_path.read_bytes()
                content_type = "text/html" if src_path.suffix.lower() in {".htm", ".html", ".xhtml"} else "text/plain"
                raw_text = normalize_document_text(raw_bytes, content_type=content_type, source_name=str(src_path))
                diag.local_files_read += 1
            elif inline_text:
                raw_text = normalize_document_text(inline_text, source_name=doc_id)
                content_type = "text/plain"
                diag.inline_rows_read += 1
            else:
                diag.add_skip("no source_url path or text")
                continue
        except Exception as exc:  # pragma: no cover - exact network/file failures vary
            diag.add_skip(f"fetch/read error: {type(exc).__name__}")
            continue

        if len(raw_text) < int(min_text_chars):
            diag.add_skip("normalized text too short")
            continue

        text_path = docs_dir / f"{_safe_id(doc_id)}.txt"
        _write_text_file(text_path, raw_text, overwrite=overwrite)
        out_row = {col: _norm(row.get(col)) for col in SOURCE_DOC_COLUMNS}
        out_row["source_doc_id"] = doc_id
        out_row["ticker"] = ticker
        out_row["event_time"] = event_time
        out_row["event_id"] = _norm(row.get("event_id")) or _safe_id(f"{ticker}_{event_time}_{doc_id}")
        out_row["event_type"] = _norm(row.get("event_type"), default="earnings").lower()
        out_row["event_subtype"] = _norm(row.get("event_subtype"), default="ingested_source").lower()
        out_row["release_session"] = _norm(row.get("release_session"), default="unknown").lower()
        out_row["source_type"] = _norm(row.get("source_type"), default="url_document" if source_url else "local_document").lower()
        out_row["title"] = _norm(row.get("title"), default=Path(urlparse(source_name).path).stem or doc_id)
        out_row["path"] = _relative_path(text_path, out_manifest.parent)
        out_row["text"] = raw_text if include_inline_text else ""
        out_row["fetched_at_utc"] = _now_utc_iso()
        out_row["content_type"] = content_type
        out_row["text_chars"] = len(raw_text)
        out_row["source_hash"] = hashlib.sha256(raw_text.encode("utf-8", errors="replace")).hexdigest()
        out_rows.append(out_row)
        diag.rows_written += 1
        diag.text_chars_total += len(raw_text)

    out_df = pd.DataFrame(out_rows)
    for col in SOURCE_DOC_COLUMNS:
        if col not in out_df.columns:
            out_df[col] = ""
    if not out_df.empty:
        ordered = SOURCE_DOC_COLUMNS + [c for c in out_df.columns if c not in SOURCE_DOC_COLUMNS]
        out_df = out_df[ordered]
    ensure_parent(out_manifest)
    out_df.to_csv(out_manifest, index=False)
    return out_df, diag


def _filter_filings(
    df: pd.DataFrame,
    *,
    start: str | None = None,
    end: str | None = None,
    item_filter: str | None = "2.02",
) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    if start:
        out = out[pd.to_datetime(out["filingDate"], errors="coerce") >= pd.to_datetime(start)]
    if end:
        out = out[pd.to_datetime(out["filingDate"], errors="coerce") <= pd.to_datetime(end)]
    if item_filter and "items" in out.columns:
        wanted = [s.strip() for s in str(item_filter).split(",") if s.strip()]
        if wanted:
            mask = pd.Series(False, index=out.index)
            items = out["items"].fillna("").astype(str)
            for wanted_item in wanted:
                mask = mask | items.str.contains(re.escape(wanted_item), case=False, regex=True)
            out = out[mask].copy()
    return out


def _infer_source_type(doc_meta: dict, primary_doc: str) -> str:
    name = str(doc_meta.get("name", ""))
    if name == primary_doc:
        return "sec_primary_filing"
    return "sec_exhibit"


def _sec_event_row_base(filing: pd.Series, sector_benchmark: str = "") -> dict:
    ticker = _norm(filing.get("ticker")).upper()
    form = _norm(filing.get("form"), default="filing").upper()
    accession = _norm(filing.get("accessionNumber"))
    accepted = _norm(filing.get("acceptanceDateTime"), default=_norm(filing.get("filingDate")))
    event_time = pd.to_datetime(accepted, errors="coerce")
    if pd.isna(event_time):
        event_time = pd.to_datetime(_norm(filing.get("filingDate")), errors="coerce")
    if pd.isna(event_time):
        event_time = pd.Timestamp.utcnow().tz_localize(None)
    filing_date = _norm(filing.get("filingDate"), default=event_time.strftime("%Y-%m-%d"))
    return {
        "event_id": _safe_id(f"{ticker}_{form}_{filing_date}_{accession}"),
        "ticker": ticker,
        "event_time": pd.Timestamp(event_time).isoformat(),
        "event_type": "earnings" if form == "8-K" and "2.02" in _norm(filing.get("items")) else "filing",
        "event_subtype": f"sec_{form.lower().replace('-', '_')}",
        "release_session": _release_session_from_acceptance(accepted),
        "sector_benchmark": sector_benchmark,
        "filing_date": filing_date,
        "accession_number": accession,
        "form": form,
    }


def _document_is_text_like(name: str) -> bool:
    suffix = Path(name).suffix.lower()
    return suffix in HTML_EXTENSIONS or not suffix


def build_sec_source_document_manifest(
    client: SecClient,
    tickers: Iterable[str],
    out_manifest: str | Path,
    docs_dir: str | Path,
    *,
    forms: Iterable[str] = ("8-K",),
    start: str | None = None,
    end: str | None = None,
    item_filter: str | None = "2.02",
    limit_per_ticker: int | None = None,
    include_primary: bool = True,
    include_exhibits: bool = True,
    exhibit_pattern: str = DEFAULT_SEC_EXHIBIT_PATTERN,
    sector_benchmark: str = "",
    overwrite: bool = False,
    min_text_chars: int = 40,
) -> tuple[pd.DataFrame, IngestionDiagnostics]:
    """Download SEC filing primary docs/exhibits into a source-doc manifest.

    Defaults target 8-K Item 2.02 filings and likely earnings-release exhibits.
    The resulting manifest can be passed directly to `mre extract-facts`.
    """
    out_manifest = Path(out_manifest)
    docs_dir = Path(docs_dir)
    diag = IngestionDiagnostics()
    rows: list[dict] = []
    exhibit_re = re.compile(exhibit_pattern) if exhibit_pattern else None

    for ticker in tickers:
        filings = client.recent_filings(ticker, forms=forms)
        filings = _filter_filings(filings, start=start, end=end, item_filter=item_filter)
        if limit_per_ticker is not None:
            filings = filings.head(limit_per_ticker).copy()
        for _, filing in filings.iterrows():
            base = _sec_event_row_base(filing, sector_benchmark=sector_benchmark)
            primary_doc = _norm(filing.get("primaryDocument"))
            try:
                doc_metas = client.filing_documents(filing, include_primary=include_primary, include_exhibits=include_exhibits, exhibit_pattern=exhibit_pattern)
            except Exception as exc:  # pragma: no cover - network failures vary
                diag.add_skip(f"filing index error: {type(exc).__name__}")
                continue
            if not doc_metas:
                diag.add_skip("no matching filing documents")
                continue
            for doc_meta in doc_metas:
                diag.rows_total += 1
                name = _norm(doc_meta.get("name"))
                if not name or not _document_is_text_like(name):
                    diag.add_skip("non text document")
                    continue
                if not include_exhibits and name != primary_doc:
                    diag.add_skip("exhibit excluded")
                    continue
                if name != primary_doc and exhibit_re and not exhibit_re.search(name):
                    diag.add_skip("exhibit pattern mismatch")
                    continue
                source_url = _norm(doc_meta.get("url")) or client.filing_document_url(int(filing["cik"]), _norm(filing["accessionNumber"]), name)
                doc_id = _safe_id(f"{base['event_id']}_{Path(name).stem}")
                try:
                    text, content_type = client.fetch_document_text(source_url)
                except Exception as exc:  # pragma: no cover - network failures vary
                    diag.add_skip(f"download error: {type(exc).__name__}")
                    continue
                text = normalize_document_text(text, content_type=content_type, source_name=name)
                if len(text) < min_text_chars:
                    diag.add_skip("normalized text too short")
                    continue
                text_path = docs_dir / f"{doc_id}.txt"
                _write_text_file(text_path, text, overwrite=overwrite)
                source_type = _infer_source_type(doc_meta, primary_doc)
                rows.append(
                    {
                        "source_doc_id": doc_id,
                        "ticker": base["ticker"],
                        "event_id": base["event_id"],
                        "event_time": base["event_time"],
                        "event_type": base["event_type"],
                        "event_subtype": base["event_subtype"],
                        "release_session": base["release_session"],
                        "source_type": source_type,
                        "source_url": source_url,
                        "title": f"{base['ticker']} {base['form']} {name}",
                        "path": _relative_path(text_path, out_manifest.parent),
                        "text": "",
                        "fiscal_period_end": "",
                        "sector_benchmark": base["sector_benchmark"],
                        "notes": json.dumps(
                            {
                                "provider": "sec-edgar",
                                "accession_number": base["accession_number"],
                                "filing_date": base["filing_date"],
                                "form": base["form"],
                                "items": _norm(filing.get("items")),
                                "document_name": name,
                            },
                            sort_keys=True,
                        ),
                        "fetched_at_utc": _now_utc_iso(),
                        "content_type": content_type,
                        "text_chars": len(text),
                        "source_hash": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
                    }
                )
                diag.rows_written += 1
                diag.downloaded += 1
                diag.text_chars_total += len(text)

    out_df = pd.DataFrame(rows)
    for col in SOURCE_DOC_COLUMNS:
        if col not in out_df.columns:
            out_df[col] = ""
    if not out_df.empty:
        out_df = out_df[SOURCE_DOC_COLUMNS + [c for c in out_df.columns if c not in SOURCE_DOC_COLUMNS]]
    ensure_parent(out_manifest)
    out_df.to_csv(out_manifest, index=False)
    return out_df, diag
