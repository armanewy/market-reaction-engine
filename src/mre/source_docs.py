from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

from .paths import ensure_parent
from .sec_common import clean_text, parse_date, parse_list, read_csv_rows, write_csv_rows

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


SEC_SOURCE_DOC_COLUMNS = [
    "source_doc_id",
    "domain",
    "ticker",
    "cik",
    "form",
    "filing_accession",
    "filing_acceptance_time",
    "filing_date",
    "source_url",
    "primary_doc_url",
    "local_path",
    "item_numbers",
    "source_type",
    "source_confidence",
    "source_notes",
]

SUPPORTED_FORMS = {
    "8-K",
    "8-K/A",
    "4",
    "4/A",
    "SC 13D",
    "SC 13D/A",
    "SC 13G",
    "SC 13G/A",
}

SUPPORTED_8K_ITEMS = {
    "1.01",
    "1.02",
    "1.03",
    "1.05",
    "2.04",
    "2.06",
    "3.01",
    "4.01",
    "4.02",
    "5.02",
    "8.01",
}

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
SEC_SUBMISSIONS_FILE_URL = "https://data.sec.gov/submissions/{name}"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}"


class SecSourceError(RuntimeError):
    pass


@dataclass
class SecClient:
    user_agent: str = "MarketReactionEngine/0.8 sec-core-infrastructure"
    timeout: int = 30
    sleep_seconds: float = 0.12

    def _request(self, url: str) -> bytes:
        request = Request(url, headers={"User-Agent": self.user_agent, "Accept-Encoding": "identity"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = response.read()
        except (HTTPError, URLError) as exc:
            raise SecSourceError(f"SEC request failed for {url}: {exc}") from exc
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        return data

    def get_json(self, url: str) -> Any:
        return json.loads(self._request(url).decode("utf-8"))

    def get_text(self, url: str) -> str:
        return self._request(url).decode("utf-8", errors="replace")


def normalize_form(value: object) -> str:
    text = clean_text(value).upper()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("SC13D", "SC 13D").replace("SC13G", "SC 13G")
    return text


def normalize_item(value: object) -> str:
    text = clean_text(value)
    match = re.search(r"(\d+)\.(\d+)", text)
    if not match:
        return ""
    return f"{int(match.group(1))}.{int(match.group(2)):02d}"


def parse_item_numbers(value: object) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    found = []
    for match in re.finditer(r"(\d+)\.(\d+)", text):
        item = f"{int(match.group(1))}.{int(match.group(2)):02d}"
        if item not in found:
            found.append(item)
    return found


def parse_8k_items_from_text(text: str) -> list[str]:
    found = []
    for match in re.finditer(r"\bItem\s+(\d+)\.(\d+)\b", text or "", flags=re.IGNORECASE):
        item = f"{int(match.group(1))}.{int(match.group(2)):02d}"
        if item in SUPPORTED_8K_ITEMS and item not in found:
            found.append(item)
    return found


def parse_tickers(tickers: str | None, ticker_csv: str | Path | None = None) -> list[str]:
    values = [value.upper() for value in parse_list(tickers)]
    if ticker_csv:
        rows, columns = read_csv_rows(ticker_csv)
        ticker_col = "ticker" if "ticker" in columns else (columns[0] if columns else "")
        for row in rows:
            ticker = clean_text(row.get(ticker_col)).upper()
            if ticker:
                values.append(ticker)
    deduped = []
    for ticker in values:
        if ticker not in deduped:
            deduped.append(ticker)
    return deduped


def validate_forms(forms: list[str]) -> list[str]:
    normalized = [normalize_form(form) for form in forms]
    invalid = [form for form in normalized if form not in SUPPORTED_FORMS]
    if invalid:
        raise ValueError(f"Unsupported SEC form(s): {', '.join(invalid)}")
    return normalized


def validate_items(items: list[str]) -> list[str]:
    normalized = [normalize_item(item) for item in items]
    normalized = [item for item in normalized if item]
    invalid = [item for item in normalized if item not in SUPPORTED_8K_ITEMS]
    if invalid:
        raise ValueError(f"Unsupported 8-K item(s): {', '.join(invalid)}")
    deduped = []
    for item in normalized:
        if item not in deduped:
            deduped.append(item)
    return deduped


def build_ticker_cik_map(client: SecClient) -> dict[str, str]:
    data = client.get_json(SEC_TICKERS_URL)
    mapping: dict[str, str] = {}
    records = data.values() if isinstance(data, dict) else data
    for record in records:
        ticker = clean_text(record.get("ticker")).upper()
        cik_raw = clean_text(record.get("cik_str"))
        if ticker and cik_raw:
            mapping[ticker] = str(int(cik_raw)).zfill(10)
    return mapping


def _filing_rows(recent: Mapping[str, list[Any]]) -> list[dict[str, Any]]:
    if not recent:
        return []
    length = max((len(value) for value in recent.values() if isinstance(value, list)), default=0)
    rows: list[dict[str, Any]] = []
    for index in range(length):
        row = {}
        for key, values in recent.items():
            if isinstance(values, list) and index < len(values):
                row[key] = values[index]
        rows.append(row)
    return rows


def collect_company_filings(cik10: str, client: SecClient) -> list[dict[str, Any]]:
    submission = client.get_json(SEC_SUBMISSIONS_URL.format(cik10=cik10))
    filings = _filing_rows(submission.get("filings", {}).get("recent", {}))
    for file_info in submission.get("filings", {}).get("files", []) or []:
        name = clean_text(file_info.get("name"))
        if not name:
            continue
        extra = client.get_json(SEC_SUBMISSIONS_FILE_URL.format(name=name))
        filings.extend(_filing_rows(extra))
    return filings


def _archive_urls(cik10: str, accession: str, primary_document: str) -> tuple[str, str]:
    cik_int = str(int(cik10))
    accession_nodash = accession.replace("-", "")
    base = SEC_ARCHIVES_URL.format(cik=cik_int, accession_nodash=accession_nodash)
    primary_url = f"{base}/{primary_document}" if primary_document else base
    return base, primary_url


def _local_doc_path(docs_dir: str | Path, domain: str, ticker: str, form: str, accession: str, primary_document: str) -> Path:
    safe_form = form.replace("/", "_").replace(" ", "_")
    safe_doc = primary_document or "filing-index.txt"
    return Path(docs_dir) / domain / ticker.upper() / safe_form / accession.replace("-", "") / safe_doc


def _source_doc_id(domain: str, ticker: str, form: str, accession: str) -> str:
    raw = f"{domain}_{ticker}_{form}_{accession}"
    return re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_").lower()


def discover_sec_source_documents(
    *,
    domain: str,
    tickers: list[str],
    forms: list[str],
    items: list[str] | None,
    start: str,
    end: str,
    docs_dir: str | Path,
    client: SecClient | None = None,
) -> list[dict[str, object]]:
    if not domain:
        raise ValueError("domain is required")
    if not tickers:
        raise ValueError("At least one ticker is required")

    client = client or SecClient()
    wanted_forms = set(validate_forms(forms))
    wanted_items = set(validate_items(items or []))
    start_date = parse_date(start)
    end_date = parse_date(end)
    if start_date is None or end_date is None:
        raise ValueError("start and end must be ISO dates")
    if end_date < start_date:
        raise ValueError("end must be on or after start")

    ticker_map = build_ticker_cik_map(client)
    rows: list[dict[str, object]] = []
    for ticker in tickers:
        ticker_upper = ticker.upper()
        cik10 = ticker_map.get(ticker_upper)
        if not cik10 and ticker_upper.isdigit():
            cik10 = str(int(ticker_upper)).zfill(10)
        if not cik10:
            continue

        for filing in collect_company_filings(cik10, client):
            form = normalize_form(filing.get("form"))
            filing_date = parse_date(filing.get("filingDate"))
            if form not in wanted_forms or filing_date is None:
                continue
            if filing_date < start_date or filing_date > end_date:
                continue

            accession = clean_text(filing.get("accessionNumber"))
            primary_document = clean_text(filing.get("primaryDocument"))
            source_url, primary_doc_url = _archive_urls(cik10, accession, primary_document)
            local_path = _local_doc_path(docs_dir, domain, ticker_upper, form, accession, primary_document)
            notes: list[str] = []
            source_confidence = 0.95
            item_numbers = parse_item_numbers(filing.get("items"))
            if form.startswith("8-K") and not item_numbers and primary_document:
                try:
                    text = client.get_text(primary_doc_url)
                    ensure_parent(local_path)
                    local_path.write_text(text, encoding="utf-8", errors="replace")
                    item_numbers = parse_8k_items_from_text(text)
                    if item_numbers:
                        notes.append("item_numbers_parsed_from_primary_document")
                        source_confidence = 0.85
                except SecSourceError as exc:
                    notes.append(f"primary_document_download_failed: {exc}")
                    source_confidence = 0.65
            elif primary_document:
                try:
                    text = client.get_text(primary_doc_url)
                    ensure_parent(local_path)
                    local_path.write_text(text, encoding="utf-8", errors="replace")
                except SecSourceError as exc:
                    notes.append(f"primary_document_download_failed: {exc}")
                    source_confidence = 0.65

            if form.startswith("8-K"):
                if wanted_items and not (set(item_numbers) & wanted_items):
                    continue
                if not item_numbers:
                    notes.append("item_numbers_not_reported")
                    source_confidence = min(source_confidence, 0.70)
            else:
                item_numbers = []

            rows.append(
                {
                    "source_doc_id": _source_doc_id(domain, ticker_upper, form, accession),
                    "domain": domain,
                    "ticker": ticker_upper,
                    "cik": cik10,
                    "form": form,
                    "filing_accession": accession,
                    "filing_acceptance_time": clean_text(filing.get("acceptanceDateTime")),
                    "filing_date": filing_date.isoformat(),
                    "source_url": source_url,
                    "primary_doc_url": primary_doc_url,
                    "local_path": str(local_path),
                    "item_numbers": ";".join(item_numbers),
                    "source_type": "sec_filing",
                    "source_confidence": f"{source_confidence:.2f}",
                    "source_notes": "; ".join(notes),
                }
            )

    rows.sort(key=lambda row: (str(row["ticker"]), str(row["filing_date"]), str(row["filing_accession"])))
    return rows


def write_sec_source_documents(
    out_path: str | Path,
    *,
    domain: str,
    tickers: str | None,
    ticker_csv: str | Path | None,
    forms: str,
    items: str | None,
    start: str,
    end: str,
    docs_dir: str | Path,
    client: SecClient | None = None,
) -> list[dict[str, object]]:
    parsed_tickers = parse_tickers(tickers, ticker_csv)
    rows = discover_sec_source_documents(
        domain=domain,
        tickers=parsed_tickers,
        forms=parse_list(forms),
        items=parse_list(items),
        start=start,
        end=end,
        docs_dir=docs_dir,
        client=client,
    )
    write_csv_rows(out_path, rows, SEC_SOURCE_DOC_COLUMNS)
    return rows
