from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re

import numpy as np
import pandas as pd

from .events import make_event_template
from .ingestion import IngestionDiagnostics, build_sec_source_document_manifest
from .paths import ensure_parent
from .prices import load_price_csv
from .sec import SecClient
from .source_docs import SourceDocument, load_source_documents


AMOUNT_RE = re.compile(r"\$?\s*(?P<num>-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*(?P<unit>billion|bn|b|million|mn|m)?", re.I)
SHARES_RE = re.compile(r"(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<unit>million|mn|m)?\s+shares", re.I)
PRICE_RE = re.compile(r"\$\s*(?P<num>\d+(?:\.\d+)?)\s+per\s+share", re.I)
OFFERING_PRICE_RE = re.compile(
    r"(?:public offering price|offering price|price to the public|purchase price|sale price|priced at|at a price(?:\s+to\s+the\s+public)?\s+of|price of)\s*(?:of\s*)?\$\s*(?P<num>\d+(?:\.\d+)?)\s+per(?:\s+share)?",
    re.I,
)
PRICE_PER_SHARE_OF_RE = re.compile(
    r"(?:effective\s+purchase\s+price|purchase\s+price|price)\s+per\s+share\s+of\s*\$\s*(?P<num>\d+(?:\.\d+)?)",
    re.I,
)

CAPITAL_RAISE_SEC_FORMS = ("8-K", "S-1", "S-3", "424B2", "424B3", "424B4", "424B5", "424B7")
CAPITAL_RAISE_8K_ITEMS = "1.01,2.03,3.02,8.01"
CAPITAL_RAISE_EXHIBIT_PATTERN = r"(?i)(ex[-_]?|exhibit|99|sales[-_ ]agreement|purchase[-_ ]agreement|securities[-_ ]purchase|placement|offering|atm|note|press)"
MONTH_DATE_RE = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2},\s+(?P<year>20\d{2}|19\d{2})\b",
    re.I,
)


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


def _event_year(doc: SourceDocument) -> int | None:
    ts = pd.to_datetime(doc.event_time, errors="coerce")
    if pd.isna(ts):
        return None
    return int(ts.year)


def _references_prior_dated_transaction(segment: str, doc: SourceDocument) -> bool:
    """Reject historical background transactions inside later prospectuses.

    Prospectus supplements often recap financings from prior years. Those
    amounts are useful background, but they are not the current event payload.
    """

    year = _event_year(doc)
    if year is None:
        return False
    years = [int(m.group("year")) for m in MONTH_DATE_RE.finditer(segment)]
    if not years:
        return False
    low = segment.lower()
    transaction_words = ("issued", "sold", "received gross proceeds", "completed", "entered into")
    return min(years) < year and any(w in low for w in transaction_words)


def _is_fee_table_segment(segment: str) -> bool:
    low = segment.lower()
    return any(
        phrase in low
        for phrase in (
            "rule 457",
            "registration fee",
            "filing fee",
            "fee table",
            "proposed maximum aggregate offering price",
            "calculated pursuant",
            "estimated solely for the purpose of calculating",
        )
    )


def _is_assumed_offering_math(segment: str) -> bool:
    low = segment.lower()
    return (
        "assumed offering price" in low
        or "last reported sale price" in low
        or "actual number of shares" in low
        or "will vary based" in low
    )


def _is_percentage_match(segment: str, match: re.Match[str]) -> bool:
    tail = segment[match.end() : match.end() + 20].lower()
    return tail.lstrip().startswith("%") or tail.lstrip().startswith("percent") or tail.lstrip().startswith("per cent")


def _amount_match_has_money_context(segment: str, match: re.Match[str]) -> bool:
    token = match.group(0)
    if "$" in token or (match.group("unit") or "").strip():
        return True
    after = segment[match.end() : match.end() + 24].lower()
    before = segment[max(0, match.start() - 12) : match.start()].lower()
    return any(unit in after for unit in ("million", "billion", "mn", "bn")) or "$" in before


def _valid_money_match(segment: str, match: re.Match[str]) -> bool:
    if _is_percentage_match(segment, match):
        return False
    return _amount_match_has_money_context(segment, match)


def _price_match_is_bad_context(segment: str, match: re.Match[str]) -> bool:
    around = segment[max(0, match.start() - 80) : match.end() + 80].lower()
    before = segment[max(0, match.start() - 45) : match.start()].lower()
    after = segment[match.end() : match.end() + 45].lower()
    if re.search(r"par\s+value\s*$", before) or re.search(r"par\s+value\s*\$?\s*$", before):
        return True
    if "exercise price" in before or "exercise price" in after:
        return True
    if "exercise price" in around and not any(w in before for w in ["public offering price", "price to the public", "purchase price per share"]):
        return True
    if "net tangible book value" in around or "immediate dilution" in around:
        return True
    return False


def _money(match: re.Match[str], default_unit: str = "") -> float:
    num = float(match.group("num").replace(",", ""))
    unit = (match.group("unit") or default_unit or "").lower()
    if unit in {"billion", "bn", "b"}:
        return num * 1_000_000_000.0
    if unit in {"million", "mn", "m"}:
        return num * 1_000_000.0
    return num


def _money_after_terms(segment: str, terms: list[str]) -> tuple[float, re.Match[str] | None]:
    low = segment.lower()
    best_pos = None
    for term in terms:
        pos = low.find(term)
        if pos >= 0 and (best_pos is None or pos < best_pos):
            best_pos = pos
    if best_pos is None:
        return np.nan, None
    tail = segment[best_pos:]
    match = AMOUNT_RE.search(tail)
    if not match:
        return np.nan, None
    if not _valid_money_match(tail, match):
        return np.nan, None
    after = tail[match.end() : match.end() + 25].lower()
    default_unit = ""
    if not match.group("unit"):
        if "billion" in after or re.search(r"\bbn\b", after):
            default_unit = "billion"
        elif "million" in after or re.search(r"\bmn\b|\bm\b", after):
            default_unit = "million"
    return _money(match, default_unit=default_unit), match


def _convertible_principal_money(segment: str) -> tuple[float, re.Match[str] | None]:
    before = re.search(
        r"(?P<amount>\$?\s*\d{1,3}(?:,\d{3})*(?:\.\d+)?|\$?\s*\d+(?:\.\d+)?)\s*(?P<unit>billion|bn|b|million|mn|m)?\s+(?:aggregate\s+)?principal amount",
        segment,
        flags=re.IGNORECASE,
    )
    if before:
        money = AMOUNT_RE.search(before.group("amount") + (" " + before.group("unit") if before.group("unit") else ""))
        if money and _valid_money_match(before.group(0), money):
            return _money(money), money
    return _money_after_terms(segment, ["aggregate principal amount", "principal amount"])


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


def _fact_selection_priority(fact_or_row: CapitalRaiseFact | pd.Series | dict) -> int:
    if isinstance(fact_or_row, CapitalRaiseFact):
        name = fact_or_row.fact_name
        evidence = fact_or_row.evidence_text
    else:
        name = str(fact_or_row.get("fact_name", "") or "")
        evidence = str(fact_or_row.get("evidence_text", "") or "")
    low = evidence.lower()
    priority = 0
    if any(w in low for w in ["entered into securities purchase", "public offering price", "gross proceeds", "issued $", "issued and sold"]):
        priority += 30
    if name == "price_per_share" and any(w in low for w in ["public offering price", "price to the public", "priced its underwritten"]):
        priority += 40
    if name == "price_per_share" and any(w in low for w in ["underwriters have agreed to purchase", "purchase price per share to be paid by the underwriters"]):
        priority -= 15
    if name == "shares_offered" and any(w in low for w in ["public offering", "issuance and sale", "offering of", "priced its underwritten", "priced its public offering"]):
        priority += 25
    if name == "shares_offered" and any(w in low for w in ["up to", "option", "additional", "upon exercise", "warrant shares", "issuable upon"]):
        priority -= 35
    if "announced the pricing of its offering" in low or "priced $" in low:
        priority += 25
    if name == "convertible_principal" and "issued $" in low and "aggregate principal amount" in low:
        priority += 35
    if name == "convertible_principal" and "announced its intention to offer" in low:
        priority -= 25
    if any(w in low for w in ["authorized denomination", "minimum denomination", "per $1,000 principal", "per $1,000 principal amount"]):
        priority -= 80
    if any(w in low for w in ["assumed offering price", "last reported sale price", "actual number of shares", "will vary based"]):
        priority -= 70
    if any(w in low for w in ["net tangible book value", "immediate dilution"]):
        priority -= 70
    if _is_fee_table_segment(evidence):
        priority -= 90
    if "underwriters of the offering to purchase up to an additional" in low or "option stock" in low:
        priority -= 60
    return priority


def infer_financing_event_type(text: str) -> tuple[str, str, float]:
    low = text.lower()
    if "registered direct offering" in low:
        return "registered_direct_offering", "registered direct offering language", 0.86
    if "private placement" in low:
        return "private_placement", "private placement language", 0.80
    if "public offering" in low and ("common stock" in low or "ordinary shares" in low):
        if any(w in low for w in ["priced", "closed", "completed", "sold", "agreed to sell", "entered into a securities purchase agreement", "gross proceeds"]):
            return "completed_equity_offering", "public common-stock offering transaction language", 0.87
        return "announced_equity_offering", "public common-stock offering announcement language", 0.82
    if "convertible" in low and ("note" in low or "debenture" in low):
        return "convertible_note_offering", "convertible note/debt language", 0.88
    if "at-the-market" in low or "at the market" in low or re.search(r"\batm\b", low):
        if any(w in low for w in ["sold", "sales under", "net proceeds from sales", "gross proceeds from sales"]) and "may sell" not in low:
            return "atm_program_usage_reported", "at-the-market usage language", 0.86
        return "atm_program_created", "at-the-market offering language", 0.88
    if "shelf registration" in low or "shelf offering" in low or "form s-3" in low:
        return "shelf_registration", "shelf registration language", 0.82
    if "prospectus supplement" in low:
        return "prospectus_supplement", "prospectus supplement language", 0.76
    if "going concern" in low:
        return "going_concern_warning", "going concern language", 0.86
    if "liquidity" in low and any(w in low for w in ["substantial doubt", "cash runway", "working capital", "continue as a going concern"]):
        return "liquidity_warning", "liquidity stress language", 0.78
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
        fee_table = _is_fee_table_segment(seg)
        assumed_math = _is_assumed_offering_math(seg)
        prior_dated_transaction = _references_prior_dated_transaction(seg, doc)
        if "use of proceeds" in low or "use the net proceeds" in low or "use the proceeds" in low:
            facts.append(_fact(doc, "use_of_proceeds", seg[:500], "text", seg, 0.70, "use_of_proceeds_sentence"))
        if "underwriter" in low or "placement agent" in low or "sales agent" in low:
            facts.append(_fact(doc, "underwriter_or_agent", seg[:300], "text", seg, 0.68, "agent_sentence"))

        if ("gross proceeds" in low or "aggregate gross proceeds" in low) and not fee_table and not prior_dated_transaction:
            val, money = _money_after_terms(seg, ["aggregate gross proceeds", "gross proceeds"])
            if money:
                facts.append(_fact(doc, "gross_proceeds", val, "usd", seg, 0.88, "gross_proceeds_sentence"))
                facts.append(_fact(doc, "offering_amount", val, "usd", seg, 0.84, "gross_proceeds_sentence"))
        elif "net proceeds" in low and not fee_table and not prior_dated_transaction:
            val, money = _money_after_terms(seg, ["net proceeds"])
            if money:
                facts.append(_fact(doc, "net_proceeds", val, "usd", seg, 0.82, "net_proceeds_sentence"))
        elif ("aggregate offering price" in low or "aggregate purchase price" in low or "up to" in low) and not fee_table and not prior_dated_transaction:
            val, money = _money_after_terms(seg, ["aggregate offering price", "aggregate purchase price", "up to"])
            if money and any(w in low for w in ["offering", "program", "sale", "sell", "securities"]):
                if event_type == "atm_program_created":
                    name = "atm_capacity"
                elif event_type == "shelf_registration":
                    name = "shelf_capacity"
                else:
                    name = "offering_amount"
                facts.append(_fact(doc, name, val, "usd", seg, 0.80, "offering_amount_sentence"))

        share_match = SHARES_RE.search(seg)
        if (
            share_match
            and any(w in low for w in ["offer", "offering", "sale", "sell", "issued"])
            and not fee_table
            and not assumed_math
            and not prior_dated_transaction
            and "underwriters of the offering to purchase up to an additional" not in low
            and "upon conversion" not in low
            and "maximum conversion rate" not in low
            and "shares of our class a common stock to be outstanding" not in low
            and "shares of common stock to be outstanding" not in low
            and "number of shares" not in low
        ):
            facts.append(_fact(doc, "shares_offered", _shares(share_match), "shares", seg, 0.84, "shares_offered_sentence"))
        price_matches = list(OFFERING_PRICE_RE.finditer(seg))
        price_matches.extend(PRICE_PER_SHARE_OF_RE.finditer(seg))
        if not price_matches and "par value" not in low and not assumed_math and any(w in low for w in ["offering price", "purchase price", "priced at", "at a price"]):
            fallback_match = PRICE_RE.search(seg)
            if fallback_match:
                price_matches.append(fallback_match)
        for price_match in price_matches:
            if fee_table or assumed_math or prior_dated_transaction:
                continue
            elif _price_match_is_bad_context(seg, price_match):
                continue
            elif "net tangible book value" in low or "immediate dilution" in low:
                continue
            elif ("exercise price" in low or "warrant" in low) and not any(w in low for w in ["offering price", "purchase price", "price to the public", "at a price of", "gross proceeds"]):
                continue
            else:
                confidence = 0.90 if "gross proceeds" in low else 0.86
                facts.append(_fact(doc, "price_per_share", float(price_match.group("num")), "usd_per_share", seg, confidence, "price_per_share_sentence"))

        if event_type == "convertible_note_offering" and ("principal amount" in low or "aggregate principal" in low) and not fee_table:
            if any(w in low for w in ["authorized denomination", "minimum denomination", "per $1,000 principal", "per $1,000 principal amount"]):
                continue
            if any(w in low for w in ["exchange agreement", "exchange agreements", "exchange transaction", "exchanged for"]) and not any(
                w in low for w in ["issued", "priced", "offering of"]
            ):
                continue
            val, money = _convertible_principal_money(seg)
            if money:
                facts.append(_fact(doc, "convertible_principal", val, "usd", seg, 0.84, "convertible_principal_sentence"))
        if "conversion price" in low:
            price_match = PRICE_RE.search(seg) or re.search(r"\$\s*(?P<num>\d+(?:\.\d+)?)", seg)
            if price_match:
                facts.append(_fact(doc, "conversion_price", float(price_match.group("num")), "usd_per_share", seg, 0.78, "conversion_price_sentence"))
    return _dedupe_facts(facts)


def _dedupe_facts(facts: list[CapitalRaiseFact]) -> list[CapitalRaiseFact]:
    best: dict[str, CapitalRaiseFact] = {}
    for fact in facts:
        current = best.get(fact.fact_name)
        if current is None or (fact.confidence, _fact_selection_priority(fact)) > (current.confidence, _fact_selection_priority(current)):
            best[fact.fact_name] = fact
    return sorted(best.values(), key=lambda f: f.fact_name)


def _to_float(value: object) -> float:
    return float(pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0])


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _amount_from(row: dict | pd.Series, columns: list[str]) -> tuple[float, str, float]:
    for col in columns:
        val = _to_float(row.get(col, np.nan))
        if pd.notna(val):
            conf = _to_float(row.get(f"{col}_confidence", np.nan))
            if pd.isna(conf):
                conf = 0.70
            return val, col, conf
    return np.nan, "", np.nan


def derive_capital_raise_fields(row: dict | pd.Series) -> dict[str, object]:
    event_type = str(row.get("financing_event_type") or "unknown")
    completed_types = {
        "completed_equity_offering",
        "registered_direct_offering",
        "private_placement",
        "convertible_note_offering",
        "atm_program_usage_reported",
    }
    capacity_types = {"atm_program_created", "shelf_registration"}
    common_stock_dilution_types = {
        "completed_equity_offering",
        "registered_direct_offering",
        "private_placement",
        "atm_program_usage_reported",
    }

    shares = _to_float(row.get("shares_offered", np.nan))
    price = _to_float(row.get("price_per_share", np.nan))
    implied_amount = shares * price if pd.notna(shares) and pd.notna(price) else np.nan

    if event_type == "convertible_note_offering":
        amount, source, confidence = _amount_from(row, ["convertible_principal", "gross_proceeds", "offering_amount", "net_proceeds"])
    elif event_type == "atm_program_created":
        amount, source, confidence = _amount_from(row, ["atm_capacity", "offering_amount"])
    elif event_type == "shelf_registration":
        amount, source, confidence = _amount_from(row, ["shelf_capacity", "offering_amount"])
    else:
        amount, source, confidence = _amount_from(row, ["gross_proceeds", "offering_amount", "net_proceeds"])

    should_prefer_implied = (
        pd.notna(amount)
        and pd.notna(implied_amount)
        and event_type in common_stock_dilution_types
        and amount < 1_000_000
        and implied_amount >= 1_000_000
    )
    if (pd.isna(amount) and pd.notna(implied_amount)) or should_prefer_implied:
        amount = implied_amount
        source = "shares_offered_x_price_per_share"
        share_conf = _to_float(row.get("shares_offered_confidence", np.nan))
        price_conf = _to_float(row.get("price_per_share_confidence", np.nan))
        confidence = min(v for v in [share_conf, price_conf, 0.78] if pd.notna(v))

    going_concern = _bool_value(row.get("going_concern_warning", False))
    liquidity_warning = _bool_value(row.get("liquidity_warning", False))
    completed = event_type in completed_types
    capacity_only = event_type in capacity_types
    if event_type == "prospectus_supplement" and not completed and pd.isna(shares) and pd.isna(price):
        capacity_only = True

    return {
        "financing_amount_best": amount,
        "financing_amount_source": source,
        "financing_amount_confidence": confidence,
        "offering_price": price,
        "immediate_dilution_flag": event_type in common_stock_dilution_types,
        "capacity_only_flag": capacity_only,
        "completed_financing_flag": completed,
        "going_concern_flag": going_concern,
        "liquidity_stress_flag": bool(going_concern or liquidity_warning),
    }


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


def build_capital_raise_sec_source_documents(
    client: SecClient,
    tickers: list[str],
    out_manifest: str | Path,
    docs_dir: str | Path,
    *,
    start: str | None = None,
    end: str | None = None,
    forms: list[str] | None = None,
    item_filter: str = CAPITAL_RAISE_8K_ITEMS,
    limit_per_ticker: int | None = None,
    sector_benchmark: str = "",
    overwrite: bool = False,
    min_text_chars: int = 40,
) -> tuple[pd.DataFrame, IngestionDiagnostics]:
    """Build a capital-raise-focused SEC source-document manifest.

    8-K rows are item-filtered to financing-relevant items. Registration
    statements and prospectus supplements usually do not have 8-K item strings,
    so they are fetched separately without item filtering.
    """
    forms = [f.upper().strip() for f in (forms or list(CAPITAL_RAISE_SEC_FORMS)) if str(f).strip()]
    out_manifest = Path(out_manifest)
    tmp_paths: list[Path] = []
    frames: list[pd.DataFrame] = []
    combined = IngestionDiagnostics()

    def add_diag(diag: IngestionDiagnostics) -> None:
        combined.rows_total += diag.rows_total
        combined.rows_written += diag.rows_written
        combined.rows_skipped += diag.rows_skipped
        combined.downloaded += diag.downloaded
        combined.local_files_read += diag.local_files_read
        combined.inline_rows_read += diag.inline_rows_read
        combined.text_chars_total += diag.text_chars_total
        for reason, count in diag.skipped_reasons.items():
            combined.skipped_reasons[reason] = combined.skipped_reasons.get(reason, 0) + int(count)

    def collect_for_ticker(ticker: str, *, selected_forms: tuple[str, ...], selected_item_filter: str | None, label: str, include_exhibits: bool) -> None:
        tmp = out_manifest.parent / f".{out_manifest.stem}_{ticker}_{label}_tmp.csv"
        tmp_paths.append(tmp)
        try:
            df, diag = build_sec_source_document_manifest(
                client,
                tickers=[ticker],
                out_manifest=tmp,
                docs_dir=docs_dir,
                forms=selected_forms,
                start=start,
                end=end,
                item_filter=selected_item_filter,
                limit_per_ticker=limit_per_ticker,
                include_primary=True,
                include_exhibits=include_exhibits,
                exhibit_pattern=CAPITAL_RAISE_EXHIBIT_PATTERN,
                sector_benchmark=sector_benchmark,
                overwrite=overwrite,
                min_text_chars=min_text_chars,
            )
        except Exception as exc:  # pragma: no cover - exact SEC/ticker failures vary
            combined.add_skip(f"{label} ticker error: {type(exc).__name__}")
            return
        frames.append(df)
        add_diag(diag)

    if "8-K" in forms:
        for ticker in tickers:
            collect_for_ticker(ticker.upper(), selected_forms=("8-K",), selected_item_filter=item_filter, label="8k", include_exhibits=True)

    other_forms = [f for f in forms if f != "8-K"]
    if other_forms:
        for ticker in tickers:
            collect_for_ticker(ticker.upper(), selected_forms=tuple(other_forms), selected_item_filter=None, label="registration", include_exhibits=False)

    out = pd.concat([f for f in frames if not f.empty], ignore_index=True) if frames else pd.DataFrame()
    if not out.empty:
        out = out.drop_duplicates(["source_doc_id"]).sort_values(["ticker", "event_time", "source_doc_id"]).reset_index(drop=True)
        out["event_type"] = "financing"
        out["event_subtype"] = out["event_subtype"].replace("", "capital_raise_source")
        out["notes"] = out["notes"].fillna("").astype(str) + " capital_raise_dilution_candidate=true"
    ensure_parent(out_manifest)
    out.to_csv(out_manifest, index=False)
    for tmp in tmp_paths:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    combined.rows_written = int(len(out))
    return out, combined


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
            ranked = group.copy()
            ranked["_selection_priority"] = ranked.apply(_fact_selection_priority, axis=1)
            for _, fact in ranked.sort_values(["confidence", "_selection_priority"], ascending=[False, False]).drop_duplicates("fact_name").iterrows():
                name = fact["fact_name"]
                row[name] = fact["value"]
                row[f"{name}_confidence"] = fact["confidence"]
                row[f"{name}_evidence"] = fact["evidence_text"]
            row.update(derive_capital_raise_fields(row))
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
        amount = pd.to_numeric(pd.Series([row.get("financing_amount_best")]), errors="coerce").iloc[0]
        magnitude = "unknown"
        if pd.notna(amount):
            magnitude = "high" if amount >= 250_000_000 else "medium" if amount >= 50_000_000 else "low"
        completed = _bool_value(row.get("completed_financing_flag", False))
        capacity_only = _bool_value(row.get("capacity_only_flag", False))
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
                "surprise_direction": "negative" if completed else "unknown",
                "surprise_magnitude": magnitude,
                "materiality": 0.7 if magnitude == "high" and completed else 0.4 if capacity_only else 0.5,
                "sector_benchmark": "",
                "notes": "Capital-raise parser candidate; review transaction-vs-capacity classification, offering size, price, source timing, and market-cap context before modeling.",
                "review_status": "unreviewed",
                "label_quality": "machine_candidate",
                "source_doc_ids": row.get("source_doc_ids", ""),
                "evidence_status": "source_backed",
                **{c: row.get(c, "") for c in features.columns if c not in {"ticker", "event_id", "event_time", "source_type", "source_url", "source_doc_ids"}},
            }
        )
    make_event_template(out_path, rows)
    return pd.read_csv(out_path)


def classify_capital_raise_audit_failure(row: dict | pd.Series) -> str:
    if str(row.get("status", "ok")) == "ok":
        return ""
    fact = str(row.get("fact_name", "") or "").lower()
    evidence = str(row.get("evidence_text", "") or "").lower()
    if "par value" in evidence and fact == "price_per_share":
        return "par_value_false_price"
    if "exercise price" in evidence and fact == "price_per_share":
        return "exercise_price_false_price"
    if "conversion price" in evidence and fact == "price_per_share":
        return "conversion_price_false_offering_price"
    if "warrant" in evidence and fact == "price_per_share":
        return "warrant_terms_false_common_stock_price"
    if "rule 457" in evidence or "registration fee" in evidence or "filing fee" in evidence:
        return "fee_table_amount_false_gross_proceeds"
    if "assumed offering price" in evidence or "last reported sale price" in evidence:
        return "estimated_maximum_offering_amount_false_completed_raise"
    if "maximum aggregate offering price" in evidence or "proposed maximum" in evidence:
        return "estimated_maximum_offering_amount_false_completed_raise"
    if "one-half percent" in evidence or "percent" in evidence or "%" in evidence:
        return "atm_commission_percent_false_capacity"
    if "underwriters of the offering to purchase up to an additional" in evidence or "option stock" in evidence:
        return "underwriter_option_false_shelf_capacity"
    if "exchange agreement" in evidence or "exchange transaction" in evidence or "exchanged for" in evidence:
        return "convertible_exchange_false_new_financing"
    if MONTH_DATE_RE.search(evidence):
        return "prior_transaction_reference"
    if fact in {"atm_capacity", "shelf_capacity"} and "may offer" in evidence:
        return "capacity_only_ambiguous_amount"
    if fact == "convertible_principal":
        return "convertible_principal_wrong"
    if fact in {"gross_proceeds", "offering_amount", "net_proceeds"}:
        return "gross_proceeds_wrong_amount"
    if fact == "shares_offered":
        return "shares_offered_wrong"
    if fact == "price_per_share":
        return "price_per_share_wrong"
    return "ambiguous_event_type"


CAPITAL_RAISE_SLICE_LABELS = {
    "completed_common_stock": "A. completed common-stock offerings / registered directs",
    "atm_programs": "B. ATM program creation / ATM usage",
    "convertible_debt": "C. convertible debt",
    "shelf_prospectus": "D. shelf registrations / prospectus supplements",
    "liquidity_warnings": "E. going-concern / liquidity warnings",
    "other": "Other / ambiguous",
}


def classify_capital_raise_slice(row: dict | pd.Series) -> str:
    event_type = str(row.get("financing_event_type", row.get("event_subtype", "")) or "").strip()
    security_type = str(row.get("security_type", "") or "").strip()
    fact_name = str(row.get("fact_name", "") or "").strip()
    if event_type in {"going_concern_warning", "liquidity_warning"} or fact_name in {"going_concern_warning", "liquidity_warning"}:
        return "liquidity_warnings"
    if event_type == "convertible_note_offering" or security_type == "convertible_notes" or fact_name in {"convertible_principal", "conversion_price"}:
        return "convertible_debt"
    if event_type in {"atm_program_created", "atm_program_usage_reported"} or fact_name == "atm_capacity":
        return "atm_programs"
    if event_type in {"shelf_registration", "prospectus_supplement"} or fact_name == "shelf_capacity":
        return "shelf_prospectus"
    if event_type in {"completed_equity_offering", "registered_direct_offering"} and security_type in {"", "common_stock", "ordinary_shares", "unknown"}:
        return "completed_common_stock"
    if event_type == "private_placement" and security_type == "common_stock":
        return "completed_common_stock"
    return "other"


def _audit_events_with_features(errors: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    if errors.empty:
        out = errors.copy()
        out["slice"] = pd.Series(dtype=str)
        return out
    feature_cols = [
        c
        for c in [
            "event_id",
            "financing_event_type",
            "security_type",
            "completed_financing_flag",
            "capacity_only_flag",
            "immediate_dilution_flag",
        ]
        if c in features.columns
    ]
    merged = errors.merge(features[feature_cols].drop_duplicates("event_id"), on="event_id", how="left") if feature_cols else errors.copy()
    merged["slice"] = merged.apply(classify_capital_raise_slice, axis=1)
    return merged


def capital_raise_audit_triage_summary(
    errors: pd.DataFrame,
    features: pd.DataFrame,
    enriched: pd.DataFrame | None = None,
    *,
    min_audit_accuracy: float = 0.90,
    min_selected_rows: int = 80,
    preferred_selected_rows: int = 100,
    min_completed_rows: int = 60,
    min_market_cap_rows: int = 40,
    min_discount_rows: int = 40,
    min_oos_predictions: int = 30,
    min_train: int = 40,
) -> dict[str, object]:
    audited = _audit_events_with_features(errors, features)
    slice_rows: dict[str, dict[str, object]] = {}
    for slice_name in CAPITAL_RAISE_SLICE_LABELS:
        group = audited[audited["slice"] == slice_name] if "slice" in audited.columns else pd.DataFrame()
        total = int(len(group))
        ok = int((group.get("status", pd.Series(dtype=str)) == "ok").sum()) if total else 0
        slice_rows[slice_name] = {
            "label": CAPITAL_RAISE_SLICE_LABELS[slice_name],
            "audit_rows": total,
            "audit_correct": ok,
            "audit_accuracy": float(ok / total) if total else 0.0,
            "audit_pass": bool(total > 0 and ok / total >= min_audit_accuracy),
            "failure_count": int(total - ok),
        }

    coverage_rows: dict[str, dict[str, object]] = {}
    if enriched is not None and not enriched.empty:
        frame = enriched.copy()
        frame["slice"] = frame.apply(classify_capital_raise_slice, axis=1)
        reviewed = frame[frame.get("review_status", pd.Series("", index=frame.index)).astype(str).eq("reviewed")]
        for slice_name in CAPITAL_RAISE_SLICE_LABELS:
            group = reviewed[reviewed["slice"] == slice_name]
            completed = group[group.get("completed_financing_flag", pd.Series(False, index=group.index)).map(_bool_value)] if not group.empty else group
            coverage_rows[slice_name] = {
                "reviewed_usable_rows": int(len(group)),
                "completed_financing_rows": int(len(completed)),
                "financing_amount_pct_market_cap_rows": int(group.get("financing_amount_pct_market_cap", pd.Series(index=group.index, dtype=float)).notna().sum()) if not group.empty else 0,
                "discount_to_last_close_pct_rows": int(group.get("discount_to_last_close_pct", pd.Series(index=group.index, dtype=float)).notna().sum()) if not group.empty else 0,
                "likely_oos_predictions_min_train": max(0, int(len(group)) - int(min_train)),
            }
    else:
        coverage_rows = {k: {} for k in CAPITAL_RAISE_SLICE_LABELS}

    for slice_name, metrics in slice_rows.items():
        coverage = coverage_rows.get(slice_name, {})
        metrics.update(coverage)
        coverage_pass = (
            int(coverage.get("reviewed_usable_rows", 0)) >= min_selected_rows
            and int(coverage.get("completed_financing_rows", 0)) >= min_completed_rows
            and int(coverage.get("financing_amount_pct_market_cap_rows", 0)) >= min_market_cap_rows
            and int(coverage.get("discount_to_last_close_pct_rows", 0)) >= min_discount_rows
            and int(coverage.get("likely_oos_predictions_min_train", 0)) >= min_oos_predictions
        )
        metrics["model_slice_gate_pass"] = bool(metrics.get("audit_pass", False) and coverage_pass)

    failures_by_reason = {}
    failures_by_fact = {}
    failures_by_subtype = {}
    failures_by_slice = {}
    if not audited.empty:
        bad = audited[audited["status"] != "ok"]
        failures_by_reason = {str(k): int(v) for k, v in bad.get("failure_reason", pd.Series(dtype=str)).value_counts(dropna=False).items()}
        failures_by_fact = {str(k): int(v) for k, v in bad.get("fact_name", pd.Series(dtype=str)).value_counts(dropna=False).items()}
        failures_by_subtype = {str(k): int(v) for k, v in bad.get("financing_event_type", pd.Series(dtype=str)).fillna("unknown").value_counts(dropna=False).items()}
        failures_by_slice = {str(k): int(v) for k, v in bad.get("slice", pd.Series(dtype=str)).value_counts(dropna=False).items()}

    passing_slices = [k for k, v in slice_rows.items() if v.get("model_slice_gate_pass")]
    audit_passing_slices = [k for k, v in slice_rows.items() if v.get("audit_pass")]
    if passing_slices:
        decision = "model-ready slice found"
        recommendation = f"narrow first model to {CAPITAL_RAISE_SLICE_LABELS[passing_slices[0]]}"
    elif audit_passing_slices:
        decision = "continue corpus buildout for clean slice"
        recommendation = f"parser audit passes for {CAPITAL_RAISE_SLICE_LABELS[audit_passing_slices[0]]}, but model coverage gates are not fully met."
    else:
        completed = slice_rows.get("completed_common_stock", {})
        if int(completed.get("reviewed_usable_rows", 0)) >= min_selected_rows:
            decision = "harden selected slice"
            recommendation = "No slice passes audit gates. Harden completed common-stock / registered-direct extraction first; it has the most model-relevant transaction payload."
        else:
            decision = "continue corpus buildout"
            recommendation = "No slice passes audit gates or model coverage gates. Build or audit a narrower corpus before modeling."

    return {
        "gold_rows": int(len(audited)),
        "correct_rows": int((audited.get("status", pd.Series(dtype=str)) == "ok").sum()) if not audited.empty else 0,
        "overall_accuracy": float((audited.get("status", pd.Series(dtype=str)) == "ok").mean()) if not audited.empty else 0.0,
        "failures_by_reason": failures_by_reason,
        "failures_by_fact_type": failures_by_fact,
        "failures_by_event_subtype": failures_by_subtype,
        "failures_by_slice": failures_by_slice,
        "slices": slice_rows,
        "decision": decision,
        "recommendation": recommendation,
    }


def write_capital_raise_audit_triage_report(
    errors_path: str | Path,
    features_path: str | Path,
    enriched_path: str | Path | None,
    out_path: str | Path,
) -> dict[str, object]:
    errors = pd.read_csv(errors_path)
    features = pd.read_csv(features_path)
    enriched = _load_optional_context(enriched_path) if enriched_path else pd.DataFrame()
    summary = capital_raise_audit_triage_summary(errors, features, enriched)
    out = ensure_parent(out_path)
    lines = [
        "# Capital Raise Audit Triage and Scope Narrowing",
        "",
        "This is a parser/data-readiness report, not a prediction result.",
        "",
        "## Decision",
        "",
        f"- decision: {summary['decision']}",
        f"- recommendation: {summary['recommendation']}",
        "",
        "## Overall Audit",
        "",
        f"- gold_rows: {summary['gold_rows']}",
        f"- correct_rows: {summary['correct_rows']}",
        f"- overall_accuracy: {summary['overall_accuracy']:.3f}",
        "",
        "## Failure Counts By Class",
        "",
    ]
    for key, val in summary["failures_by_reason"].items():
        lines.append(f"- {key}: {val}")
    lines.extend(["", "## Failure Counts By Fact Type", ""])
    for key, val in summary["failures_by_fact_type"].items():
        lines.append(f"- {key}: {val}")
    lines.extend(["", "## Failure Counts By Event Subtype", ""])
    for key, val in summary["failures_by_event_subtype"].items():
        lines.append(f"- {key}: {val}")
    lines.extend(["", "## Slice Audit And Coverage", ""])
    for slice_name, metrics in summary["slices"].items():
        lines.extend(
            [
                f"### {metrics['label']}",
                "",
                f"- audit_rows: {metrics.get('audit_rows', 0)}",
                f"- audit_correct: {metrics.get('audit_correct', 0)}",
                f"- audit_accuracy: {metrics.get('audit_accuracy', 0):.3f}",
                f"- audit_pass: {'PASS' if metrics.get('audit_pass') else 'FAIL'}",
                f"- reviewed_usable_rows: {metrics.get('reviewed_usable_rows', 0)}",
                f"- completed_financing_rows: {metrics.get('completed_financing_rows', 0)}",
                f"- financing_amount_pct_market_cap_rows: {metrics.get('financing_amount_pct_market_cap_rows', 0)}",
                f"- discount_to_last_close_pct_rows: {metrics.get('discount_to_last_close_pct_rows', 0)}",
                f"- likely_oos_predictions_min_train: {metrics.get('likely_oos_predictions_min_train', 0)}",
                f"- model_slice_gate_pass: {'PASS' if metrics.get('model_slice_gate_pass') else 'FAIL'}",
                "",
            ]
        )
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return summary


def validate_capital_raise_parser(
    facts: pd.DataFrame,
    gold: pd.DataFrame,
    out_errors: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    if gold.empty:
        errors = pd.DataFrame()
        return errors, {"gold_rows": 0, "status": "no_gold_rows"}

    pred = facts.copy()
    pred["confidence"] = pd.to_numeric(pred.get("confidence"), errors="coerce")
    pred["_selection_priority"] = pred.apply(_fact_selection_priority, axis=1)
    pred = pred.sort_values(["confidence", "_selection_priority"], ascending=[False, False]).drop_duplicates(["event_id", "fact_name"], keep="first")

    key_cols = ["event_id", "fact_name"]
    merged = gold.merge(pred, on=key_cols, how="left", suffixes=("_gold", "_pred"))
    tolerance_by_unit = {
        "usd": 1_000_000.0,
        "shares": 1.0,
        "usd_per_share": 0.01,
        "boolean": 0.0,
    }
    rows: list[dict] = []
    for _, row in merged.iterrows():
        unit = str(row.get("unit_gold") or row.get("unit_pred") or "").strip()
        expected_raw = row.get("expected_value")
        actual_raw = row.get("value")
        tolerance_raw = pd.to_numeric(pd.Series([row.get("tolerance")]), errors="coerce").iloc[0]
        tolerance = float(tolerance_raw) if pd.notna(tolerance_raw) else float(tolerance_by_unit.get(unit, 0.0))
        expected_present = _bool_value(row.get("expected_present", True))

        if not expected_present:
            if pd.isna(actual_raw):
                status = "ok"
            else:
                status = "false_positive"
            rows.append(
                {
                    **{c: row.get(c) for c in key_cols},
                    "expected_value": expected_raw,
                    "actual_value": actual_raw,
                    "unit": unit,
                    "tolerance": tolerance,
                    "abs_error": np.nan,
                    "status": status,
                    "confidence": row.get("confidence"),
                    "evidence_text": row.get("evidence_text_pred", row.get("evidence_text", "")),
                }
            )
            continue

        if unit in {"category", "text"}:
            expected = _norm_space(expected_raw).lower()
            actual = _norm_space(actual_raw).lower() if pd.notna(actual_raw) else ""
            status = "ok" if actual == expected else "wrong_value" if actual else "missed"
            abs_error = np.nan
        elif unit == "boolean":
            expected = _bool_value(expected_raw)
            actual = _bool_value(actual_raw) if pd.notna(actual_raw) else np.nan
            status = "ok" if actual == expected else "wrong_value" if pd.notna(actual_raw) else "missed"
            abs_error = np.nan
        else:
            expected = pd.to_numeric(pd.Series([expected_raw]), errors="coerce").iloc[0]
            actual = pd.to_numeric(pd.Series([actual_raw]), errors="coerce").iloc[0]
            if pd.isna(actual):
                status = "missed"
                abs_error = np.nan
            else:
                abs_error = abs(float(actual) - float(expected))
                status = "ok" if abs_error <= tolerance else "wrong_value"
        rows.append(
            {
                **{c: row.get(c) for c in key_cols},
                "expected_value": expected_raw,
                "actual_value": actual_raw,
                "unit": unit,
                "tolerance": tolerance,
                "abs_error": abs_error,
                "status": status,
                "confidence": row.get("confidence"),
                "evidence_text": row.get("evidence_text_pred", row.get("evidence_text", "")),
            }
        )

    errors = pd.DataFrame(rows)
    if not errors.empty:
        errors["failure_reason"] = errors.apply(classify_capital_raise_audit_failure, axis=1)
    metrics = {}
    for fact_name, group in errors.groupby("fact_name"):
        total = int(len(group))
        ok = int((group["status"] == "ok").sum())
        metrics[fact_name] = {"gold_rows": total, "correct": ok, "recall_on_gold": ok / total if total else 0.0}
    failure_reasons = {}
    if not errors.empty and "failure_reason" in errors.columns:
        non_ok = errors[errors["status"] != "ok"]
        failure_reasons = {str(k): int(v) for k, v in non_ok["failure_reason"].value_counts().items()}
    report = {
        "gold_rows": int(len(errors)),
        "correct_rows": int((errors["status"] == "ok").sum()),
        "row_accuracy": float((errors["status"] == "ok").mean()) if len(errors) else 0.0,
        "by_fact": metrics,
        "failure_reasons": failure_reasons,
    }
    if out_errors:
        ensure_parent(out_errors)
        errors.to_csv(out_errors, index=False)
    return errors, report


def build_sec_shares_outstanding_context(
    client: SecClient,
    events_path: str | Path,
    out_path: str | Path,
) -> tuple[pd.DataFrame, dict[str, object]]:
    events = pd.read_csv(events_path)
    tickers = sorted({str(t).upper() for t in events.get("ticker", pd.Series(dtype=str)).dropna().unique()})
    rows: list[dict] = []
    diagnostics = {"tickers_total": len(tickers), "tickers_ok": 0, "tickers_skipped": 0, "skipped_reasons": {}}

    def skip(reason: str) -> None:
        diagnostics["tickers_skipped"] = int(diagnostics["tickers_skipped"]) + 1
        skipped = diagnostics["skipped_reasons"]
        skipped[reason] = skipped.get(reason, 0) + 1

    for ticker in tickers:
        try:
            facts = client.companyfacts(ticker)
        except Exception as exc:  # pragma: no cover - network/SEC ticker failures vary
            skip(f"companyfacts error: {type(exc).__name__}")
            continue
        share_facts = (
            facts.get("facts", {})
            .get("dei", {})
            .get("EntityCommonStockSharesOutstanding", {})
            .get("units", {})
            .get("shares", [])
        )
        if not share_facts:
            skip("missing EntityCommonStockSharesOutstanding")
            continue
        cik = int(facts.get("cik", 0) or 0)
        for fact in share_facts:
            val = pd.to_numeric(pd.Series([fact.get("val")]), errors="coerce").iloc[0]
            filed = pd.to_datetime(fact.get("filed"), errors="coerce")
            end = pd.to_datetime(fact.get("end"), errors="coerce")
            if pd.isna(val) or val <= 0 or pd.isna(filed):
                continue
            accn = str(fact.get("accn", "") or "")
            source_url = ""
            if cik and accn:
                source_url = SecClient.filing_base_url(cik, accn)
            rows.append(
                {
                    "ticker": ticker,
                    "asof_date": end.date().isoformat() if pd.notna(end) else "",
                    "filed_at": filed.date().isoformat(),
                    "shares_outstanding_before_event": float(val),
                    "source_type": "sec_companyfacts_dei",
                    "source_url": source_url,
                    "accession_number": accn,
                    "form": fact.get("form", ""),
                    "confidence": 0.82,
                    "notes": "SEC companyfacts DEI EntityCommonStockSharesOutstanding; join uses latest filed_at <= event_time.",
                }
            )
        diagnostics["tickers_ok"] = int(diagnostics["tickers_ok"]) + 1

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.drop_duplicates(["ticker", "filed_at", "shares_outstanding_before_event", "accession_number"])
        out = out.sort_values(["ticker", "filed_at", "asof_date"]).reset_index(drop=True)
    ensure_parent(out_path)
    out.to_csv(out_path, index=False)
    diagnostics["rows"] = int(len(out))
    return out, diagnostics


def write_capital_raise_parser_audit_report(report: dict[str, object], errors: pd.DataFrame, out_path: str | Path) -> Path:
    out = ensure_parent(out_path)
    lines = [
        "# Capital Raise Parser Audit Report",
        "",
        "This validates parser facts against a human-reviewed gold set. It is a parser-quality report, not a model result.",
        "",
        "## Metrics",
        "",
        f"- gold_rows: {report.get('gold_rows', 0)}",
        f"- correct_rows: {report.get('correct_rows', 0)}",
        f"- row_accuracy: {report.get('row_accuracy', 0):.3f}" if "row_accuracy" in report else f"- status: {report.get('status', 'unknown')}",
        "",
        "## By Fact",
        "",
    ]
    for fact_name, metrics in (report.get("by_fact", {}) or {}).items():
        lines.append(f"- {fact_name}: {metrics}")
    failure_reasons = report.get("failure_reasons", {}) or {}
    if failure_reasons:
        lines.extend(["", "## Failure Reasons", ""])
        for reason, count in failure_reasons.items():
            lines.append(f"- {reason}: {count}")
    bad = errors[errors["status"] != "ok"] if not errors.empty and "status" in errors.columns else pd.DataFrame()
    if not bad.empty:
        lines.extend(["", "## Non-OK Rows", ""])
        for _, row in bad.head(75).iterrows():
            reason = row.get("failure_reason", "")
            lines.append(f"- {row['event_id']} / {row['fact_name']}: {row['status']} reason={reason} expected={row['expected_value']} actual={row['actual_value']}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def _load_optional_context(path: str | Path | None) -> pd.DataFrame:
    if not path:
        return pd.DataFrame()
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)


def _lookup_external_context(row: pd.Series, context: pd.DataFrame, value_col: str) -> float:
    matched = _lookup_external_context_row(row, context)
    if matched.empty or value_col not in matched.index:
        return np.nan
    return _to_float(matched.get(value_col))


def _lookup_external_context_row(row: pd.Series, context: pd.DataFrame) -> pd.Series:
    if context.empty:
        return pd.Series(dtype=object)
    event_id = str(row.get("event_id", ""))
    if "event_id" in context.columns:
        matched = context[context["event_id"].astype(str) == event_id]
        if not matched.empty:
            return matched.iloc[0]

    ticker = str(row.get("ticker", "")).upper()
    if "ticker" not in context.columns:
        return pd.Series(dtype=object)
    subset = context[context["ticker"].astype(str).str.upper() == ticker].copy()
    if subset.empty:
        return pd.Series(dtype=object)
    sort_col = ""
    if "filed_at" in subset.columns:
        sort_col = "filed_at"
    elif "asof_date" in subset.columns:
        sort_col = "asof_date"
    if sort_col:
        subset[sort_col] = pd.to_datetime(subset[sort_col], errors="coerce").dt.tz_localize(None)
        event_time = pd.to_datetime(row.get("event_time"), errors="coerce")
        if pd.notna(event_time):
            event_time = event_time.tz_localize(None) if getattr(event_time, "tzinfo", None) else event_time
            subset = subset[subset[sort_col] <= event_time]
        subset = subset.sort_values(sort_col, ascending=False)
    if subset.empty:
        return pd.Series(dtype=object)
    return subset.iloc[0]


def _anchor_price(prices: pd.DataFrame, event_time: object, release_session: object) -> tuple[pd.Timestamp | None, float]:
    ts = pd.to_datetime(event_time, errors="coerce")
    if pd.isna(ts):
        return None, np.nan
    ts = ts.tz_localize(None) if getattr(ts, "tzinfo", None) else ts
    date = ts.normalize()
    session = str(release_session or "").lower().strip()
    include_same_day = session in {"after_close", "intraday", "market_hours", "unknown", ""}
    eligible = prices[prices["date"] <= date] if include_same_day else prices[prices["date"] < date]
    if eligible.empty:
        return None, np.nan
    last = eligible.iloc[-1]
    return pd.to_datetime(last["date"]), _to_float(last["adj_close"])


def _window_return(prices: pd.DataFrame, anchor_date: pd.Timestamp | None, window: int) -> float:
    if anchor_date is None:
        return np.nan
    dates = prices["date"]
    idx_matches = prices.index[dates == anchor_date].tolist()
    if not idx_matches:
        return np.nan
    idx = idx_matches[-1]
    start_idx = idx - int(window)
    if start_idx < 0:
        return np.nan
    start = _to_float(prices.iloc[start_idx]["adj_close"])
    end = _to_float(prices.iloc[idx]["adj_close"])
    if pd.isna(start) or pd.isna(end) or start == 0:
        return np.nan
    return end / start - 1.0


def enrich_capital_raise_context(
    events_path: str | Path,
    prices_dir: str | Path,
    out_path: str | Path,
    *,
    benchmark_ticker: str = "SPY",
    market_caps_path: str | Path | None = None,
    shares_outstanding_path: str | Path | None = None,
) -> pd.DataFrame:
    events = pd.read_csv(events_path)
    market_caps = _load_optional_context(market_caps_path)
    shares_context = _load_optional_context(shares_outstanding_path)

    price_cache: dict[str, pd.DataFrame] = {}
    benchmark_prices = load_price_csv(prices_dir, benchmark_ticker.upper())

    enriched_rows: list[dict] = []
    for _, row in events.iterrows():
        out = row.to_dict()
        ticker = str(row.get("ticker", "")).upper()
        status: list[str] = []
        try:
            prices = price_cache.setdefault(ticker, load_price_csv(prices_dir, ticker))
        except FileNotFoundError:
            prices = pd.DataFrame()
            status.append("missing_ticker_prices")

        anchor_date = None
        last_close = np.nan
        if not prices.empty:
            anchor_date, last_close = _anchor_price(prices, row.get("event_time"), row.get("release_session"))
            if pd.isna(last_close):
                status.append("missing_pre_event_close")
        out["price_anchor_date"] = anchor_date.date().isoformat() if anchor_date is not None else ""
        out["last_close_before_event"] = last_close

        offering_price = _to_float(row.get("offering_price", row.get("price_per_share", np.nan)))
        out["offering_price"] = offering_price
        out["discount_to_last_close_pct"] = (offering_price - last_close) / last_close if pd.notna(offering_price) and pd.notna(last_close) and last_close else np.nan

        shares_lookup = pd.Series(dtype=object)
        shares_outstanding = _to_float(row.get("shares_outstanding_before_event", np.nan))
        if pd.isna(shares_outstanding):
            shares_lookup = _lookup_external_context_row(row, shares_context)
            shares_outstanding = _to_float(shares_lookup.get("shares_outstanding_before_event", np.nan)) if not shares_lookup.empty else np.nan
        out["shares_outstanding_before_event"] = shares_outstanding
        if not shares_lookup.empty:
            out["shares_outstanding_source"] = shares_lookup.get("source_type", "")
            out["shares_outstanding_source_url"] = shares_lookup.get("source_url", "")
            asof = pd.to_datetime(shares_lookup.get("asof_date", ""), errors="coerce")
            filed = pd.to_datetime(shares_lookup.get("filed_at", ""), errors="coerce")
            out["shares_outstanding_asof_date"] = asof.date().isoformat() if pd.notna(asof) else str(shares_lookup.get("asof_date", "") or "")
            out["shares_outstanding_filed_at"] = filed.date().isoformat() if pd.notna(filed) else str(shares_lookup.get("filed_at", "") or "")
            out["shares_outstanding_confidence"] = shares_lookup.get("confidence", np.nan)

        market_cap = _to_float(row.get("market_cap_before_event", np.nan))
        if pd.isna(market_cap):
            market_cap = _lookup_external_context(row, market_caps, "market_cap_before_event")
        if pd.isna(market_cap) and pd.notna(shares_outstanding) and pd.notna(last_close):
            market_cap = shares_outstanding * last_close
        out["market_cap_before_event"] = market_cap

        shares_offered = _to_float(row.get("shares_offered", np.nan))
        out["estimated_dilution_pct"] = shares_offered / shares_outstanding if pd.notna(shares_offered) and pd.notna(shares_outstanding) and shares_outstanding else np.nan

        financing_amount = _to_float(row.get("financing_amount_best", np.nan))
        atm_capacity = _to_float(row.get("atm_capacity", np.nan))
        convertible_principal = _to_float(row.get("convertible_principal", np.nan))
        out["financing_amount_pct_market_cap"] = financing_amount / market_cap if pd.notna(financing_amount) and pd.notna(market_cap) and market_cap else np.nan
        out["atm_capacity_pct_market_cap"] = atm_capacity / market_cap if pd.notna(atm_capacity) and pd.notna(market_cap) and market_cap else np.nan
        out["convertible_principal_pct_market_cap"] = convertible_principal / market_cap if pd.notna(convertible_principal) and pd.notna(market_cap) and market_cap else np.nan

        for window in (20, 60):
            stock_ret = _window_return(prices, anchor_date, window) if not prices.empty else np.nan
            bench_anchor, _ = _anchor_price(benchmark_prices, row.get("event_time"), row.get("release_session"))
            bench_ret = _window_return(benchmark_prices, bench_anchor, window)
            out[f"pre_event_return_{window}d"] = stock_ret
            out[f"pre_event_benchmark_return_{window}d"] = bench_ret
            out[f"pre_event_market_adjusted_return_{window}d"] = stock_ret - bench_ret if pd.notna(stock_ret) and pd.notna(bench_ret) else np.nan

        out["capital_raise_context_status"] = "ok" if not status else ";".join(sorted(set(status)))
        enriched_rows.append(out)

    enriched = pd.DataFrame(enriched_rows)
    ensure_parent(out_path)
    enriched.to_csv(out_path, index=False)
    return enriched


def capital_raise_readiness_summary(events: pd.DataFrame, *, min_train: int = 40, parser_errors: pd.DataFrame | None = None) -> dict[str, object]:
    if events.empty:
        return {"rows": 0, "decision": "continue corpus buildout", "reason": "no rows"}

    review_status = events.get("review_status", pd.Series([""] * len(events), index=events.index)).fillna("").astype(str).str.lower()
    usable = events[~review_status.isin({"rejected", "drop", "dropped"})].copy()
    usable_status = usable.get("review_status", pd.Series([""] * len(usable), index=usable.index)).fillna("").astype(str).str.lower()
    reviewed = usable[usable_status.eq("reviewed")].copy() if "review_status" in events.columns else usable
    if reviewed.empty:
        reviewed = usable

    completed = reviewed[reviewed.get("completed_financing_flag", pd.Series(False, index=reviewed.index)).map(_bool_value)]
    capacity = reviewed[reviewed.get("capacity_only_flag", pd.Series(False, index=reviewed.index)).map(_bool_value)]
    ambiguous = events[review_status.isin({"ambiguous", "needs_review", "unreviewed"})]

    metrics: dict[str, object] = {
        "candidate_rows": int(len(events)),
        "reviewed_usable_rows": int(len(reviewed)),
        "completed_financing_rows": int(len(completed)),
        "capacity_only_rows": int(len(capacity)),
        "ambiguous_or_unreviewed_rows": int(len(ambiguous)),
        "rejected_rows": int(review_status.isin({"rejected", "drop", "dropped"}).sum()),
        "rows_with_financing_amount_best": int(reviewed.get("financing_amount_best", pd.Series(index=reviewed.index, dtype=float)).notna().sum()),
        "rows_with_price_per_share": int((reviewed.get("price_per_share", pd.Series(index=reviewed.index, dtype=float)).notna() | reviewed.get("offering_price", pd.Series(index=reviewed.index, dtype=float)).notna()).sum()),
        "rows_with_discount_to_last_close_pct": int(reviewed.get("discount_to_last_close_pct", pd.Series(index=reviewed.index, dtype=float)).notna().sum()),
        "rows_with_market_cap_before_event": int(reviewed.get("market_cap_before_event", pd.Series(index=reviewed.index, dtype=float)).notna().sum()),
        "rows_with_financing_amount_pct_market_cap": int(reviewed.get("financing_amount_pct_market_cap", pd.Series(index=reviewed.index, dtype=float)).notna().sum()),
        "rows_with_estimated_dilution_pct": int(reviewed.get("estimated_dilution_pct", pd.Series(index=reviewed.index, dtype=float)).notna().sum()),
        "likely_oos_predictions_min_train": int(max(0, len(reviewed) - int(min_train))),
    }

    blockers = []
    gates = {
        "reviewed_usable_events_80_min": metrics["reviewed_usable_rows"] >= 80,
        "reviewed_usable_events_100_preferred": metrics["reviewed_usable_rows"] >= 100,
        "completed_financing_events_60": metrics["completed_financing_rows"] >= 60,
        "financing_amount_pct_market_cap_rows_40": metrics["rows_with_financing_amount_pct_market_cap"] >= 40,
        "discount_rows_40": metrics["rows_with_discount_to_last_close_pct"] >= 40,
        "likely_oos_predictions_30": metrics["likely_oos_predictions_min_train"] >= 30,
    }
    if parser_errors is not None:
        ok_count = int((parser_errors.get("status", pd.Series(dtype=str)) == "ok").sum()) if not parser_errors.empty else 0
        audit_rows = int(len(parser_errors))
        audit_accuracy = ok_count / audit_rows if audit_rows else 0.0
        metrics["parser_audit_rows"] = audit_rows
        metrics["parser_audit_accuracy"] = float(audit_accuracy)
        gates["parser_audit_pass"] = bool(audit_rows >= 60 and audit_accuracy >= 0.90)
    for gate, passed in gates.items():
        if not passed:
            blockers.append(gate)
    metrics["gates"] = gates
    metrics["top_missing_fields_blocking_modeling"] = blockers[:]
    if all(gates.values()):
        metrics["decision"] = "model-ready"
        metrics["reason"] = "corpus clears first-pass non-modeling readiness gates"
    else:
        metrics["decision"] = "continue corpus buildout"
        metrics["reason"] = "readiness gates still failing: " + ", ".join(blockers)
    return metrics


def write_capital_raise_readiness_report(
    events_path: str | Path,
    out_path: str | Path,
    *,
    min_train: int = 40,
    parser_errors_path: str | Path | None = None,
) -> dict[str, object]:
    events = pd.read_csv(events_path)
    parser_errors = pd.read_csv(parser_errors_path) if parser_errors_path else None
    summary = capital_raise_readiness_summary(events, min_train=min_train, parser_errors=parser_errors)
    out = ensure_parent(out_path)
    lines = [
        "# Capital Raise Corpus Readiness Report",
        "",
        "This is a data-readiness report, not a prediction result.",
        "",
        "## Summary",
        "",
    ]
    for key, value in summary.items():
        if key in {"gates", "top_missing_fields_blocking_modeling"}:
            continue
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Gates", ""])
    for gate, passed in (summary.get("gates", {}) or {}).items():
        lines.append(f"- {gate}: {'PASS' if passed else 'FAIL'}")
    lines.extend(["", "## Top Missing Fields / Gates", ""])
    for blocker in summary.get("top_missing_fields_blocking_modeling", []) or []:
        lines.append(f"- {blocker}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
