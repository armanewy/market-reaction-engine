from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re

import numpy as np
import pandas as pd

from .events import make_event_template
from .paths import ensure_parent
from .source_docs import SourceDocument, load_source_documents


AMOUNT_RE = re.compile(r"\$?\s*(?P<num>-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*(?P<unit>billion|bn|b|million|mn|m)?", re.I)
SHARES_RE = re.compile(r"(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<unit>million|mn|m)?\s+shares", re.I)
PRICE_RE = re.compile(r"\$\s*(?P<num>\d+(?:\.\d+)?)\s+per\s+share", re.I)


@dataclass(frozen=True)
class CapitalRaiseFact:
    source_doc_id: str
    event_id: str
    ticker: str
    event_time: str
    fact_name: str
    value: str | float | bool
    unit: str
    evidence_text: str
    confidence: float
    parse_method: str
    source_type: str = ""
    source_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _segments(text: str) -> list[str]:
    parts = []
    for raw in re.split(r"(?<!\d)[\.;!?](?!\d)|\n+", str(text or "")):
        seg = _norm_space(raw)
        if 12 <= len(seg) <= 700:
            parts.append(seg)
    return parts


def _money(match: re.Match[str], default_unit: str = "") -> float:
    num = float(match.group("num").replace(",", ""))
    unit = (match.group("unit") or default_unit or "").lower()
    if unit in {"billion", "bn", "b"}:
        return num * 1_000_000_000.0
    if unit in {"million", "mn", "m"}:
        return num * 1_000_000.0
    return num


def _shares(match: re.Match[str]) -> float:
    num = float(match.group("num").replace(",", ""))
    unit = (match.group("unit") or "").lower()
    if unit in {"million", "mn", "m"}:
        return num * 1_000_000.0
    return num


def _fact(doc: SourceDocument, name: str, value: str | float | bool, unit: str, evidence: str, confidence: float, method: str) -> CapitalRaiseFact:
    return CapitalRaiseFact(
        source_doc_id=doc.source_doc_id,
        event_id=doc.event_id,
        ticker=doc.ticker,
        event_time=doc.event_time.isoformat(),
        fact_name=name,
        value=value,
        unit=unit,
        evidence_text=_norm_space(evidence),
        confidence=float(np.clip(confidence, 0.0, 0.99)),
        parse_method=method,
        source_type=doc.source_type,
        source_url=doc.source_url,
    )


def infer_financing_event_type(text: str) -> tuple[str, str, float]:
    low = text.lower()
    if "at-the-market" in low or "at the market" in low or re.search(r"\batm\b", low):
        return "atm_program", "at-the-market offering language", 0.88
    if "convertible" in low and ("note" in low or "debenture" in low):
        return "convertible_debt", "convertible note/debt language", 0.88
    if "going concern" in low:
        return "going_concern_warning", "going concern language", 0.86
    if "shelf registration" in low or "shelf offering" in low or "form s-3" in low:
        return "shelf_registration", "shelf registration language", 0.82
    if "registered direct offering" in low:
        return "registered_direct_offering", "registered direct offering language", 0.86
    if "public offering" in low and ("common stock" in low or "ordinary shares" in low):
        return "equity_offering", "public common-stock offering language", 0.86
    if "private placement" in low:
        return "private_placement", "private placement language", 0.80
    return "unknown", "", 0.30


def infer_security_type(text: str) -> tuple[str, str, float]:
    low = text.lower()
    if "convertible" in low and ("note" in low or "debenture" in low):
        return "convertible_notes", "convertible notes/debentures", 0.88
    if "common stock" in low or "common shares" in low or "ordinary shares" in low:
        return "common_stock", "common stock/share language", 0.86
    if "preferred stock" in low or "preferred shares" in low:
        return "preferred_stock", "preferred stock/share language", 0.84
    if "warrant" in low:
        return "warrants", "warrant language", 0.78
    if "units" in low:
        return "units", "unit offering language", 0.72
    return "unknown", "", 0.30


def parse_capital_raise_document(doc: SourceDocument) -> list[CapitalRaiseFact]:
    facts: list[CapitalRaiseFact] = []
    doc_text = _norm_space(doc.text)
    event_type, evidence, conf = infer_financing_event_type(doc_text[:5000])
    facts.append(_fact(doc, "financing_event_type", event_type, "category", evidence, conf, "document_keyword"))
    security_type, security_evidence, security_conf = infer_security_type(doc_text[:5000])
    facts.append(_fact(doc, "security_type", security_type, "category", security_evidence, security_conf, "document_keyword"))

    if event_type == "going_concern_warning":
        facts.append(_fact(doc, "going_concern_warning", True, "boolean", evidence, conf, "document_keyword"))
    if "liquidity" in doc_text.lower() and any(w in doc_text.lower() for w in ["substantial doubt", "cash runway", "working capital", "continue as a going concern"]):
        facts.append(_fact(doc, "liquidity_warning", True, "boolean", "liquidity / cash runway language", 0.74, "document_keyword"))

    for seg in _segments(doc.text):
        low = seg.lower()
        if "use of proceeds" in low or "use the net proceeds" in low or "use the proceeds" in low:
            facts.append(_fact(doc, "use_of_proceeds", seg[:500], "text", seg, 0.70, "use_of_proceeds_sentence"))
        if "underwriter" in low or "placement agent" in low or "sales agent" in low:
            facts.append(_fact(doc, "underwriter_or_agent", seg[:300], "text", seg, 0.68, "agent_sentence"))

        if "gross proceeds" in low or "aggregate gross proceeds" in low:
            money = AMOUNT_RE.search(seg)
            if money:
                val = _money(money)
                facts.append(_fact(doc, "gross_proceeds", val, "usd", seg, 0.88, "gross_proceeds_sentence"))
                facts.append(_fact(doc, "offering_amount", val, "usd", seg, 0.84, "gross_proceeds_sentence"))
        elif "net proceeds" in low:
            money = AMOUNT_RE.search(seg)
            if money:
                facts.append(_fact(doc, "net_proceeds", _money(money), "usd", seg, 0.82, "net_proceeds_sentence"))
        elif "aggregate offering price" in low or "aggregate purchase price" in low or "up to" in low:
            money = AMOUNT_RE.search(seg)
            if money and any(w in low for w in ["offering", "program", "sale", "sell", "securities"]):
                name = "atm_capacity" if event_type == "atm_program" else "offering_amount"
                facts.append(_fact(doc, name, _money(money), "usd", seg, 0.80, "offering_amount_sentence"))

        share_match = SHARES_RE.search(seg)
        if share_match and any(w in low for w in ["offer", "offering", "sale", "sell", "issued"]):
            facts.append(_fact(doc, "shares_offered", _shares(share_match), "shares", seg, 0.84, "shares_offered_sentence"))
        price_match = PRICE_RE.search(seg)
        if price_match:
            facts.append(_fact(doc, "price_per_share", float(price_match.group("num")), "usd_per_share", seg, 0.86, "price_per_share_sentence"))

        if event_type == "convertible_debt" and ("principal amount" in low or "aggregate principal" in low):
            money = AMOUNT_RE.search(seg)
            if money:
                facts.append(_fact(doc, "convertible_principal", _money(money), "usd", seg, 0.84, "convertible_principal_sentence"))
        if "conversion price" in low:
            price_match = PRICE_RE.search(seg) or re.search(r"\$\s*(?P<num>\d+(?:\.\d+)?)", seg)
            if price_match:
                facts.append(_fact(doc, "conversion_price", float(price_match.group("num")), "usd_per_share", seg, 0.78, "conversion_price_sentence"))
    return _dedupe_facts(facts)


def _dedupe_facts(facts: list[CapitalRaiseFact]) -> list[CapitalRaiseFact]:
    best: dict[str, CapitalRaiseFact] = {}
    for fact in facts:
        current = best.get(fact.fact_name)
        if current is None or fact.confidence > current.confidence:
            best[fact.fact_name] = fact
    return sorted(best.values(), key=lambda f: f.fact_name)


def parse_capital_raise_manifest(
    documents_path: str | Path,
    facts_out: str | Path,
    features_out: str | Path,
    events_out: str | Path,
    *,
    min_confidence: float = 0.0,
    usable_confidence: float = 0.70,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    docs = load_source_documents(documents_path)
    rows: list[dict] = []
    for doc in docs:
        for fact in parse_capital_raise_document(doc):
            if fact.confidence >= min_confidence:
                rows.append(fact.to_dict())
    facts = pd.DataFrame(rows)
    if not facts.empty:
        facts = facts.sort_values(["ticker", "event_time", "event_id", "fact_name"]).reset_index(drop=True)
    ensure_parent(facts_out)
    facts.to_csv(facts_out, index=False)

    features = pivot_capital_raise_facts(facts, features_out, min_confidence=usable_confidence)
    events = capital_raise_features_to_events(features, events_out)
    return facts, features, events


def pivot_capital_raise_facts(facts: pd.DataFrame, out_path: str | Path | None = None, *, min_confidence: float = 0.70) -> pd.DataFrame:
    if facts.empty:
        out = pd.DataFrame()
    else:
        usable = facts[pd.to_numeric(facts["confidence"], errors="coerce") >= float(min_confidence)].copy()
        rows = []
        for event_id, group in usable.groupby("event_id", sort=False):
            row = {
                "event_id": event_id,
                "ticker": group["ticker"].iloc[0],
                "event_time": group["event_time"].iloc[0],
                "source_doc_ids": ";".join(sorted(group["source_doc_id"].astype(str).unique())),
                "usable_fact_count": int(len(group)),
                "source_type": group["source_type"].iloc[0],
                "source_url": group["source_url"].iloc[0],
            }
            for _, fact in group.sort_values("confidence", ascending=False).drop_duplicates("fact_name").iterrows():
                name = fact["fact_name"]
                row[name] = fact["value"]
                row[f"{name}_confidence"] = fact["confidence"]
                row[f"{name}_evidence"] = fact["evidence_text"]
            rows.append(row)
        out = pd.DataFrame(rows)
    if out_path:
        ensure_parent(out_path)
        out.to_csv(out_path, index=False)
    return out


def capital_raise_features_to_events(features: pd.DataFrame, out_path: str | Path) -> pd.DataFrame:
    rows: list[dict] = []
    for _, row in features.iterrows():
        event_type = str(row.get("financing_event_type") or "unknown")
        ticker = str(row.get("ticker", "")).upper()
        amount = pd.to_numeric(pd.Series([row.get("offering_amount") or row.get("gross_proceeds") or row.get("atm_capacity")]), errors="coerce").iloc[0]
        magnitude = "unknown"
        if pd.notna(amount):
            magnitude = "high" if amount >= 250_000_000 else "medium" if amount >= 50_000_000 else "low"
        rows.append(
            {
                "event_id": row["event_id"],
                "ticker": ticker,
                "event_time": row["event_time"],
                "event_type": "financing",
                "summary": f"{ticker} {event_type.replace('_', ' ')} candidate from source document.",
                "event_subtype": event_type,
                "event_family": "capital_raise_dilution",
                "source_type": row.get("source_type", "source_document"),
                "source_url": row.get("source_url", ""),
                "release_session": "unknown",
                "expectedness": "unknown",
                "surprise_direction": "negative" if event_type in {"equity_offering", "registered_direct_offering", "atm_program", "convertible_debt"} else "unknown",
                "surprise_magnitude": magnitude,
                "materiality": 0.7 if magnitude == "high" else 0.5,
                "sector_benchmark": "",
                "notes": "Capital-raise parser candidate; review offering size, price, source timing, and market-cap context before modeling.",
                "review_status": "unreviewed",
                "label_quality": "machine_candidate",
                "source_doc_ids": row.get("source_doc_ids", ""),
                "evidence_status": "source_backed",
                **{c: row.get(c, "") for c in features.columns if c not in {"ticker", "event_id", "event_time", "source_type", "source_url", "source_doc_ids"}},
            }
        )
    make_event_template(out_path, rows)
    return pd.read_csv(out_path)
