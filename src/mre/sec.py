from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

from .events import make_event_template

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"


def default_user_agent() -> str:
    return os.environ.get("SEC_USER_AGENT", "market-reaction-engine/0.6 contact@example.com")


class SecClient:
    """Tiny SEC submissions client.

    SEC does not require an API key for these endpoints, but it expects a useful
    User-Agent and rate-conscious access. Set SEC_USER_AGENT to something like:

        export SEC_USER_AGENT="market-reaction-engine your-email@example.com"
    """

    def __init__(self, user_agent: str | None = None, requests_per_second: float = 5.0):
        self.user_agent = user_agent or default_user_agent()
        self.headers = {"User-Agent": self.user_agent}
        self.delay = 1.0 / max(float(requests_per_second), 0.1)
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def _get_json(self, url: str) -> dict:
        resp = self.session.get(url, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"SEC request failed {resp.status_code}: {url}\n{resp.text[:500]}")
        time.sleep(self.delay)
        return resp.json()

    def _get_response(self, url: str) -> requests.Response:
        resp = self.session.get(url, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"SEC request failed {resp.status_code}: {url}\n{resp.text[:500]}")
        time.sleep(self.delay)
        return resp

    def _get_text(self, url: str) -> tuple[str, str]:
        resp = self._get_response(url)
        return resp.text, resp.headers.get("Content-Type", "")

    def company_tickers(self) -> pd.DataFrame:
        data = self._get_json(SEC_TICKERS_URL)
        rows = list(data.values())
        df = pd.DataFrame(rows)
        df["ticker"] = df["ticker"].astype(str).str.upper()
        df["cik_str"] = df["cik_str"].astype(int)
        return df

    def ticker_to_cik(self, ticker: str) -> tuple[int, str]:
        ticker = ticker.upper().strip()
        df = self.company_tickers()
        match = df[df["ticker"] == ticker]
        if match.empty:
            raise ValueError(f"Ticker not found in SEC company_tickers.json: {ticker}")
        row = match.iloc[0]
        return int(row["cik_str"]), str(row.get("title", ticker))

    def submissions(self, ticker: str) -> dict:
        cik, _ = self.ticker_to_cik(ticker)
        return self._get_json(SEC_SUBMISSIONS_URL.format(cik10=f"{cik:010d}"))

    def companyfacts(self, ticker: str) -> dict:
        cik, _ = self.ticker_to_cik(ticker)
        return self._get_json(SEC_COMPANYFACTS_URL.format(cik10=f"{cik:010d}"))


    @staticmethod
    def filing_base_url(cik: int, accession: str) -> str:
        accession_nodash = str(accession).replace("-", "")
        return f"{SEC_ARCHIVES_BASE}/{int(cik)}/{accession_nodash}"

    def filing_document_url(self, cik: int, accession: str, document_name: str) -> str:
        return f"{self.filing_base_url(cik, accession)}/{document_name}"

    def filing_index(self, cik: int, accession: str) -> dict:
        return self._get_json(f"{self.filing_base_url(cik, accession)}/index.json")

    def filing_documents(
        self,
        filing_row: pd.Series | dict,
        *,
        include_primary: bool = True,
        include_exhibits: bool = True,
        exhibit_pattern: str = r"(?i)(ex[-_]?99|exhibit[-_ ]?99|dex99|99[._-]?1|earnings|results|press[-_ ]?release)",
    ) -> list[dict]:
        """Return text-like documents for one filing row.

        The SEC archive index usually exposes primary documents, XBRL files,
        image files, and exhibits. This helper keeps the primary document plus
        likely earnings-release exhibits by default.
        """
        cik = int(filing_row["cik"])
        accession = str(filing_row["accessionNumber"])
        primary = str(filing_row.get("primaryDocument", ""))
        idx = self.filing_index(cik, accession)
        items = idx.get("directory", {}).get("item", []) or []
        pattern = re.compile(exhibit_pattern) if exhibit_pattern else None
        out: list[dict] = []
        for item in items:
            name = str(item.get("name", ""))
            if not name:
                continue
            lower = name.lower()
            suffix = Path(lower).suffix
            if suffix and suffix not in {".htm", ".html", ".txt", ".xml", ".xhtml"}:
                continue
            is_primary = name == primary
            is_exhibit = bool(pattern.search(name)) if pattern else False
            if (is_primary and include_primary) or (is_exhibit and include_exhibits):
                row = dict(item)
                row["name"] = name
                row["url"] = self.filing_document_url(cik, accession, name)
                row["is_primary"] = is_primary
                row["is_exhibit"] = is_exhibit and not is_primary
                out.append(row)
        if include_primary and primary and not any(d.get("name") == primary for d in out):
            out.insert(0, {"name": primary, "url": self.filing_document_url(cik, accession, primary), "is_primary": True, "is_exhibit": False})
        return out

    def fetch_document_text(self, url: str) -> tuple[str, str]:
        return self._get_text(url)

    def recent_filings(self, ticker: str, forms: Iterable[str] | None = None) -> pd.DataFrame:
        forms_set = {f.upper() for f in forms} if forms else None
        cik, company_name = self.ticker_to_cik(ticker)
        data = self._get_json(SEC_SUBMISSIONS_URL.format(cik10=f"{cik:010d}"))
        recent = data.get("filings", {}).get("recent", {})
        if not recent:
            return pd.DataFrame()
        df = pd.DataFrame(recent)
        df["ticker"] = ticker.upper()
        df["company_name"] = company_name
        df["cik"] = cik
        df["form"] = df["form"].astype(str).str.upper()
        if forms_set:
            df = df[df["form"].isin(forms_set)].copy()
        return df


def _release_session_from_acceptance(acceptance: str) -> str:
    ts = pd.to_datetime(acceptance, errors="coerce")
    if pd.isna(ts):
        return "unknown"
    t = ts.time()
    # SEC acceptanceDateTime is usually Eastern time without timezone suffix.
    if t.hour < 9 or (t.hour == 9 and t.minute < 30):
        return "before_open"
    if t.hour >= 16:
        return "after_close"
    return "intraday"


def filings_to_event_template(df: pd.DataFrame, out_path: str | Path, limit: int | None = None) -> pd.DataFrame:
    rows = []
    source_cols = set(df.columns)
    for _, r in df.head(limit).iterrows():
        cik = int(r["cik"])
        accession = str(r["accessionNumber"])
        accession_nodash = accession.replace("-", "")
        primary_doc = str(r.get("primaryDocument", ""))
        url = ""
        if primary_doc:
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{primary_doc}"
        accepted = r.get("acceptanceDateTime", r.get("filingDate", ""))
        if accepted:
            event_time = pd.to_datetime(accepted, errors="coerce")
        else:
            event_time = pd.NaT
        if pd.isna(event_time):
            event_time = pd.to_datetime(r.get("filingDate"), errors="coerce")
        if pd.isna(event_time):
            event_time = pd.Timestamp.utcnow().tz_localize(None)
        form = str(r.get("form", "filing")).upper()
        ticker = str(r.get("ticker", "")).upper()
        company = str(r.get("company_name", ticker))
        rows.append(
            {
                "event_id": f"{ticker}_{form}_{str(r.get('filingDate', 'date'))}_{accession}",
                "ticker": ticker,
                "event_time": event_time.isoformat(),
                "event_type": "filing",
                "summary": f"{company} filed {form}. Curate this row before using it as a model label.",
                "event_subtype": form,
                "source_type": "sec_filing",
                "source_url": url,
                "release_session": _release_session_from_acceptance(str(accepted)),
                "expectedness": "unknown",
                "surprise_direction": "unknown",
                "surprise_magnitude": "unknown",
                "materiality": 0.5,
                "sector_benchmark": "",
                "notes": "Generated from SEC submissions API. This is a template; manually classify materiality/expectedness.",
            }
        )
    make_event_template(out_path, rows)
    return pd.DataFrame(rows)
