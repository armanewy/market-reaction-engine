from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

import pandas as pd

from .ingestion import normalize_document_text
from .paths import ensure_parent
from .sec import _release_session_from_acceptance
from .source_docs import SOURCE_DOC_COLUMNS


CYBER_8K_FORMS = ("8-K", "8-K/A")
CYBER_8K_ITEMS = ("1.05",)
CYBER_8K_EXHIBIT_PATTERN = r"(?i)(ex[-_]?99|exhibit[-_ ]?99|dex99|99[._-]?1|press[-_ ]?release|cyber|incident|security|breach|ransom)"


@dataclass
class Cyber8KSourceDiagnostics:
    tickers_total: int = 0
    filings_seen: int = 0
    filings_kept: int = 0
    docs_written: int = 0
    skipped_reasons: dict[str, int] = field(default_factory=dict)

    def add_skip(self, reason: str) -> None:
        self.skipped_reasons[reason] = self.skipped_reasons.get(reason, 0) + 1

    def to_dict(self) -> dict:
        return asdict(self)


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


def _safe_id(value: object, default: str = "doc") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", _norm(value, default=default)).strip("_")
    return cleaned[:180] or default


def _relative_path(path: Path, base_dir: Path) -> str:
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return str(path)


def _item_metadata_matches(items: object) -> bool | None:
    text = _norm(items)
    if not text:
        return None
    return any(item in text for item in CYBER_8K_ITEMS)


def _text_mentions_item_105(text: str) -> bool:
    return bool(re.search(r"\bItem\s+1\.05\b", text, flags=re.I))


def _document_is_text_like(name: str) -> bool:
    suffix = Path(name).suffix.lower()
    return suffix in {"", ".htm", ".html", ".txt", ".xml", ".xhtml"}


def _document_source_type(name: str, primary_doc: str) -> str:
    return "sec_primary_filing" if name == primary_doc else "sec_exhibit"


def _filter_by_date(df: pd.DataFrame, *, start: str | None, end: str | None) -> pd.DataFrame:
    out = df.copy()
    if start and "filingDate" in out.columns:
        out = out[pd.to_datetime(out["filingDate"], errors="coerce") >= pd.to_datetime(start)]
    if end and "filingDate" in out.columns:
        out = out[pd.to_datetime(out["filingDate"], errors="coerce") <= pd.to_datetime(end)]
    return out


def build_cyber_8k_source_documents(
    client,
    *,
    tickers: Iterable[str],
    out_manifest: str | Path,
    docs_dir: str | Path,
    start: str | None = None,
    end: str | None = None,
    limit_per_ticker: int | None = None,
    include_primary: bool = True,
    include_exhibits: bool = True,
    overwrite: bool = False,
    min_text_chars: int = 80,
) -> tuple[pd.DataFrame, Cyber8KSourceDiagnostics]:
    out_manifest = Path(out_manifest)
    docs_dir = Path(docs_dir)
    ticker_list = list(tickers)
    diagnostics = Cyber8KSourceDiagnostics(tickers_total=len(ticker_list))
    rows: list[dict] = []

    for ticker in ticker_list:
        filings = client.recent_filings(ticker, forms=CYBER_8K_FORMS)
        filings = _filter_by_date(filings, start=start, end=end)
        if limit_per_ticker is not None:
            filings = filings.head(limit_per_ticker).copy()
        diagnostics.filings_seen += int(len(filings))

        for _, filing in filings.iterrows():
            form = _norm(filing.get("form")).upper()
            if form not in CYBER_8K_FORMS:
                diagnostics.add_skip("non cyber 8-k form")
                continue
            item_match = _item_metadata_matches(filing.get("items"))
            if item_match is False:
                diagnostics.add_skip("non item 1.05 filing")
                continue
            primary_doc = _norm(filing.get("primaryDocument"))
            accession = _norm(filing.get("accessionNumber"))
            accepted_at = _norm(filing.get("acceptanceDateTime"), default=_norm(filing.get("filingDate")))
            filing_date = _norm(filing.get("filingDate"))
            event_time = pd.to_datetime(accepted_at, errors="coerce")
            if pd.isna(event_time):
                event_time = pd.to_datetime(filing_date, errors="coerce")
            cik = _norm(filing.get("cik"))
            ticker_upper = _norm(filing.get("ticker"), default=ticker).upper()
            company_name = _norm(filing.get("company_name"), default=ticker_upper)

            try:
                doc_metas = client.filing_documents(
                    filing,
                    include_primary=include_primary,
                    include_exhibits=include_exhibits,
                    exhibit_pattern=CYBER_8K_EXHIBIT_PATTERN,
                )
            except Exception as exc:  # pragma: no cover - network failures vary
                diagnostics.add_skip(f"filing index error: {type(exc).__name__}")
                continue
            if not doc_metas:
                diagnostics.add_skip("no matching filing documents")
                continue

            filing_rows: list[dict] = []
            for doc_meta in doc_metas:
                name = _norm(doc_meta.get("name"))
                if not name or not _document_is_text_like(name):
                    diagnostics.add_skip("non text document")
                    continue
                if name != primary_doc and not include_exhibits:
                    diagnostics.add_skip("exhibit excluded")
                    continue
                source_url = _norm(doc_meta.get("url")) or client.filing_document_url(int(cik), accession, name)
                try:
                    raw_text, content_type = client.fetch_document_text(source_url)
                except Exception as exc:  # pragma: no cover - network failures vary
                    diagnostics.add_skip(f"download error: {type(exc).__name__}")
                    continue
                text = normalize_document_text(raw_text, content_type=content_type, source_name=name)
                if len(text) < min_text_chars:
                    diagnostics.add_skip("normalized text too short")
                    continue
                text_item_match = _text_mentions_item_105(text)
                if item_match is None and not text_item_match:
                    diagnostics.add_skip("missing item metadata and no item 1.05 text")
                    continue

                event_id = _safe_id(f"{ticker_upper}_{form}_{filing_date}_{accession}")
                doc_id = _safe_id(f"{event_id}_{Path(name).stem}")
                text_path = docs_dir / f"{doc_id}.txt"
                if text_path.exists() and not overwrite:
                    diagnostics.add_skip("document already exists")
                    continue
                ensure_parent(text_path)
                text_path.write_text(text, encoding="utf-8")
                source_confidence = "sec_item_metadata" if item_match else "document_text_item_105"
                filing_rows.append(
                    {
                        "source_doc_id": doc_id,
                        "ticker": ticker_upper,
                        "event_id": event_id,
                        "event_time": pd.Timestamp(event_time).isoformat() if not pd.isna(event_time) else "",
                        "event_type": "cybersecurity",
                        "event_subtype": "sec_8_k_item_1_05",
                        "release_session": _release_session_from_acceptance(accepted_at),
                        "source_type": _document_source_type(name, primary_doc),
                        "source_url": source_url,
                        "title": f"{ticker_upper} {form} Item 1.05 {name}",
                        "path": _relative_path(text_path, out_manifest.parent),
                        "text": "",
                        "fiscal_period_end": "",
                        "sector_benchmark": "",
                        "notes": json.dumps(
                            {
                                "provider": "sec-edgar",
                                "company_name": company_name,
                                "cik": cik,
                                "accession": accession,
                                "filing_date": filing_date,
                                "accepted_at": accepted_at,
                                "form": form,
                                "item_numbers": _norm(filing.get("items")),
                                "primary_doc_url": _norm(filing.get("primary_doc_url")),
                                "document_name": name,
                                "source_confidence": source_confidence,
                            },
                            sort_keys=True,
                        ),
                        "cik": cik,
                        "company_name": company_name,
                        "form": form,
                        "accession": accession,
                        "filing_date": filing_date,
                        "accepted_at": accepted_at,
                        "item_numbers": _norm(filing.get("items")),
                        "primary_doc_url": _norm(filing.get("primary_doc_url")),
                        "source_confidence": source_confidence,
                        "text_chars": len(text),
                        "source_hash": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
                    }
                )

            if filing_rows:
                rows.extend(filing_rows)
                diagnostics.filings_kept += 1
                diagnostics.docs_written += len(filing_rows)

    out_df = pd.DataFrame(rows)
    for col in SOURCE_DOC_COLUMNS:
        if col not in out_df.columns:
            out_df[col] = ""
    if not out_df.empty:
        out_df = out_df[SOURCE_DOC_COLUMNS + [c for c in out_df.columns if c not in SOURCE_DOC_COLUMNS]]
    ensure_parent(out_manifest)
    out_df.to_csv(out_manifest, index=False)
    return out_df, diagnostics
