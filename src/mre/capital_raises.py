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
    r"(?:offering price|purchase price|sale price|priced at|at a price of|price of)\s*\$\s*(?P<num>\d+(?:\.\d+)?)\s+per\s+share",
    re.I,
)

CAPITAL_RAISE_SEC_FORMS = ("8-K", "S-1", "S-3", "424B2", "424B3", "424B4", "424B5", "424B7")
CAPITAL_RAISE_8K_ITEMS = "1.01,2.03,3.02,8.01"
CAPITAL_RAISE_EXHIBIT_PATTERN = r"(?i)(ex[-_]?|exhibit|99|sales[-_ ]agreement|purchase[-_ ]agreement|securities[-_ ]purchase|placement|offering|atm|note|press)"


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
        if money:
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
        if "use of proceeds" in low or "use the net proceeds" in low or "use the proceeds" in low:
            facts.append(_fact(doc, "use_of_proceeds", seg[:500], "text", seg, 0.70, "use_of_proceeds_sentence"))
        if "underwriter" in low or "placement agent" in low or "sales agent" in low:
            facts.append(_fact(doc, "underwriter_or_agent", seg[:300], "text", seg, 0.68, "agent_sentence"))

        if "gross proceeds" in low or "aggregate gross proceeds" in low:
            val, money = _money_after_terms(seg, ["aggregate gross proceeds", "gross proceeds"])
            if money:
                facts.append(_fact(doc, "gross_proceeds", val, "usd", seg, 0.88, "gross_proceeds_sentence"))
                facts.append(_fact(doc, "offering_amount", val, "usd", seg, 0.84, "gross_proceeds_sentence"))
        elif "net proceeds" in low:
            val, money = _money_after_terms(seg, ["net proceeds"])
            if money:
                facts.append(_fact(doc, "net_proceeds", val, "usd", seg, 0.82, "net_proceeds_sentence"))
        elif "aggregate offering price" in low or "aggregate purchase price" in low or "up to" in low:
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
        if share_match and any(w in low for w in ["offer", "offering", "sale", "sell", "issued"]):
            facts.append(_fact(doc, "shares_offered", _shares(share_match), "shares", seg, 0.84, "shares_offered_sentence"))
        price_match = OFFERING_PRICE_RE.search(seg)
        if not price_match and "par value" not in low and any(w in low for w in ["offering price", "purchase price", "priced at", "at a price"]):
            price_match = PRICE_RE.search(seg)
        if price_match:
            if ("exercise price" in low or "warrant" in low) and not any(w in low for w in ["offering price", "purchase price", "at a price of", "gross proceeds"]):
                pass
            else:
                confidence = 0.90 if "gross proceeds" in low else 0.86
                facts.append(_fact(doc, "price_per_share", float(price_match.group("num")), "usd_per_share", seg, confidence, "price_per_share_sentence"))

        if event_type == "convertible_note_offering" and ("principal amount" in low or "aggregate principal" in low):
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
        if current is None or fact.confidence > current.confidence:
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
            for _, fact in group.sort_values("confidence", ascending=False).drop_duplicates("fact_name").iterrows():
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
    pred = pred.sort_values("confidence", ascending=False).drop_duplicates(["event_id", "fact_name"], keep="first")

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
    metrics = {}
    for fact_name, group in errors.groupby("fact_name"):
        total = int(len(group))
        ok = int((group["status"] == "ok").sum())
        metrics[fact_name] = {"gold_rows": total, "correct": ok, "recall_on_gold": ok / total if total else 0.0}
    report = {
        "gold_rows": int(len(errors)),
        "correct_rows": int((errors["status"] == "ok").sum()),
        "row_accuracy": float((errors["status"] == "ok").mean()) if len(errors) else 0.0,
        "by_fact": metrics,
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
    bad = errors[errors["status"] != "ok"] if not errors.empty and "status" in errors.columns else pd.DataFrame()
    if not bad.empty:
        lines.extend(["", "## Non-OK Rows", ""])
        for _, row in bad.head(75).iterrows():
            lines.append(f"- {row['event_id']} / {row['fact_name']}: {row['status']} expected={row['expected_value']} actual={row['actual_value']}")
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
