from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

from .events import make_event_template
from .ingestion import IngestionDiagnostics, build_sec_source_document_manifest
from .paths import ensure_parent
from .prices import load_price_csv
from .sec import SecClient
from .source_docs import SourceDocument, load_source_documents


INSIDER_PURCHASE_DOMAIN = "insider_purchase_clusters"

INSIDER_PURCHASE_EVENT_TYPES = {
    "open_market_purchase",
    "purchase_cluster",
    "ceo_purchase",
    "cfo_purchase",
    "director_purchase",
    "ten_percent_owner_purchase",
    "planned_transaction",
    "non_open_market_transaction",
    "sale_cluster",
    "option_exercise",
    "tax_withholding",
}

PRIMARY_PURCHASE_TYPES = {
    "open_market_purchase",
    "ceo_purchase",
    "cfo_purchase",
    "director_purchase",
}

HARD_NEGATIVE_TYPES = {
    "planned_transaction",
    "non_open_market_transaction",
    "sale_cluster",
    "option_exercise",
    "tax_withholding",
}

INSIDER_FACT_COLUMNS = [
    "source_doc_id",
    "event_id",
    "ticker",
    "event_time",
    "fact_name",
    "value",
    "unit",
    "evidence_text",
    "confidence",
    "parse_method",
    "source_type",
    "source_url",
]

INSIDER_FEATURE_COLUMNS = [
    "event_id",
    "ticker",
    "event_time",
    "source_doc_ids",
    "usable_fact_count",
    "source_type",
    "source_url",
    "source_evidence_text",
    "insider_purchase_event_type",
    "transaction_code",
    "transaction_date",
    "filing_acceptance_time",
    "reporting_owner_name",
    "reporting_owner_role",
    "officer_title",
    "direct_or_indirect",
    "shares",
    "price",
    "transaction_value",
    "ownership_after",
    "10b5_1_language",
    "derivative_flag",
    "footnote_text",
    "open_market_purchase_flag",
    "officer_or_director_flag",
    "ceo_purchase_flag",
    "cfo_purchase_flag",
    "director_purchase_flag",
    "ten_percent_owner_only_flag",
    "hard_negative_flag",
    "amended_filing_flag",
    "evidence_status",
    "parser_quality_flags",
    "execution_survivability_class",
    "first_realistic_entry",
    "tradeability_after_first_entry_rationale",
    "next_open_required_flag",
    "close_to_close_explanatory_only_flag",
    "execution_survivability_gate",
    "execution_cost_stress_required",
]


@dataclass(frozen=True)
class InsiderPurchaseFact:
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


def _norm(value: object, default: str = "") -> str:
    text = str(value if value is not None else "").strip()
    if text.lower() in {"nan", "none", "null", "nat"}:
        return default
    return text or default


def _norm_space(value: object) -> str:
    return re.sub(r"\s+", " ", _norm(value)).strip()


def _to_float(value: object) -> float:
    return float(pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0])


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except Exception:
        pass
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _local(tag: str) -> str:
    return str(tag).split("}", 1)[-1]


def _children(element: ET.Element | None, name: str) -> list[ET.Element]:
    if element is None:
        return []
    return [child for child in list(element) if _local(child.tag) == name]


def _first(element: ET.Element | None, name: str) -> ET.Element | None:
    matches = _children(element, name)
    return matches[0] if matches else None


def _desc(element: ET.Element | None, path: list[str]) -> ET.Element | None:
    cur = element
    for part in path:
        cur = _first(cur, part)
        if cur is None:
            return None
    return cur


def _text(element: ET.Element | None, path: list[str] | str, default: str = "") -> str:
    if isinstance(path, str):
        path = [path]
    node = _desc(element, path)
    return _norm(node.text if node is not None else "", default=default)


def _all_desc(element: ET.Element | None, name: str) -> list[ET.Element]:
    if element is None:
        return []
    return [node for node in element.iter() if _local(node.tag) == name]


def _parse_xml(text: str) -> ET.Element:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("empty Form 4 XML document")
    start = cleaned.find("<")
    if start > 0:
        cleaned = cleaned[start:]
    return ET.fromstring(cleaned)


def _footnote_map(root: ET.Element) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in _all_desc(root, "footnote"):
        fid = _norm(node.attrib.get("id") or node.attrib.get("footnoteId"))
        if fid:
            out[fid] = _norm_space("".join(node.itertext()))
    return out


def _transaction_footnotes(transaction: ET.Element, footnotes: dict[str, str], remarks: str) -> str:
    ids: list[str] = []
    for node in _all_desc(transaction, "footnoteId"):
        fid = _norm(node.attrib.get("id"))
        if fid:
            ids.append(fid)
    texts = [footnotes[fid] for fid in ids if fid in footnotes and footnotes[fid]]
    if remarks:
        texts.append(remarks)
    return _norm_space(" ".join(dict.fromkeys(texts)))


def _owner_context(root: ET.Element) -> dict[str, str | bool]:
    names: list[str] = []
    roles: set[str] = set()
    titles: list[str] = []
    for owner in _children(root, "reportingOwner"):
        name = _text(owner, ["reportingOwnerId", "rptOwnerName"])
        if name:
            names.append(name)
        rel = _first(owner, "reportingOwnerRelationship")
        is_director = _text(rel, "isDirector").lower() in {"1", "true"}
        is_officer = _text(rel, "isOfficer").lower() in {"1", "true"}
        is_ten = _text(rel, "isTenPercentOwner").lower() in {"1", "true"}
        is_other = _text(rel, "isOther").lower() in {"1", "true"}
        if is_director:
            roles.add("director")
        if is_officer:
            roles.add("officer")
        if is_ten:
            roles.add("ten_percent_owner")
        if is_other:
            roles.add("other")
        title = _text(rel, "officerTitle")
        if title:
            titles.append(title)
    role_text = ";".join(sorted(roles))
    title_text = ";".join(dict.fromkeys(titles))
    return {
        "reporting_owner_name": ";".join(dict.fromkeys(names)),
        "reporting_owner_role": role_text,
        "officer_title": title_text,
        "director_flag": "director" in roles,
        "officer_flag": "officer" in roles,
        "ten_percent_owner_flag": "ten_percent_owner" in roles,
    }


def _has_10b5_1(text: object) -> bool:
    low = _norm_space(text).lower()
    return bool(re.search(r"10b5[- ]?1|rule\s+10b5|trading\s+plan|written\s+plan", low))


def _classify_transaction(
    *,
    transaction_code: str,
    acquired_disposed: str,
    derivative_flag: bool,
    shares: float,
    price: float,
    planned: bool,
    owner: dict[str, str | bool],
) -> tuple[str, list[str]]:
    code = transaction_code.upper().strip()
    ad = acquired_disposed.upper().strip()
    flags: list[str] = []
    if derivative_flag or code == "M":
        flags.append("derivative_or_option_exercise_not_purchase")
        return "option_exercise", flags
    if code == "F":
        flags.append("tax_withholding_not_open_market")
        return "tax_withholding", flags
    if code in {"G", "J", "A", "D"}:
        flags.append("non_open_market_code")
        return "non_open_market_transaction", flags
    if code in {"S", "D"} or ad == "D":
        flags.append("sale_or_disposition_not_purchase")
        return "sale_cluster", flags
    if code == "P":
        if planned:
            flags.append("10b5_1_or_planned_transaction")
            return "planned_transaction", flags
        if ad != "A":
            flags.append("purchase_code_without_acquired_indicator")
            return "non_open_market_transaction", flags
        if pd.isna(shares) or shares <= 0 or pd.isna(price) or price <= 0:
            flags.append("missing_positive_cash_purchase_terms")
            return "non_open_market_transaction", flags
        title = str(owner.get("officer_title", "")).lower()
        role = str(owner.get("reporting_owner_role", "")).lower()
        is_director = bool(owner.get("director_flag"))
        is_officer = bool(owner.get("officer_flag"))
        is_ten = bool(owner.get("ten_percent_owner_flag"))
        if is_ten and not (is_director or is_officer):
            flags.append("ten_percent_owner_only_needs_separate_review")
            return "ten_percent_owner_purchase", flags
        if "chief executive" in title or re.search(r"\bceo\b", title):
            return "ceo_purchase", flags
        if "chief financial" in title or re.search(r"\bcfo\b", title):
            return "cfo_purchase", flags
        if is_director:
            return "director_purchase", flags
        return "open_market_purchase", flags
    flags.append("unsupported_transaction_code")
    return "non_open_market_transaction", flags


def _fact(
    doc: SourceDocument,
    event_id: str,
    name: str,
    value: str | float | bool,
    unit: str,
    evidence: str,
    confidence: float,
    method: str,
) -> InsiderPurchaseFact:
    return InsiderPurchaseFact(
        source_doc_id=doc.source_doc_id,
        event_id=event_id,
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


def parse_insider_purchase_document(doc: SourceDocument) -> list[InsiderPurchaseFact]:
    """Parse SEC Form 4 XML into transaction-level facts.

    Only transaction code P with acquired shares, positive price/shares, no
    10b5-1 language, and an officer/director or non-10% owner context is treated
    as a primary open-market purchase candidate.
    """
    root = _parse_xml(doc.text)
    issuer = _first(root, "issuer")
    ticker = _text(issuer, "issuerTradingSymbol", default=doc.ticker).upper()
    owner = _owner_context(root)
    footnotes = _footnote_map(root)
    remarks = _text(root, "remarks")
    form_type = _text(root, ["documentType"]).upper()
    amended = form_type.endswith("/A") or form_type in {"4/A", "5/A"} or "4/A" in _norm(doc.title).upper()
    transactions = [(False, node) for node in _all_desc(root, "nonDerivativeTransaction")]
    transactions += [(True, node) for node in _all_desc(root, "derivativeTransaction")]
    if not transactions:
        return [
            _fact(
                doc,
                doc.event_id,
                "insider_purchase_event_type",
                "non_open_market_transaction",
                "category",
                "Form 4 contains no transaction rows.",
                0.45,
                "form4_xml_no_transactions",
            )
        ]

    facts: list[InsiderPurchaseFact] = []
    for idx, (derivative_flag, txn) in enumerate(transactions, start=1):
        event_id = f"{doc.event_id}_txn{idx:02d}" if len(transactions) > 1 else doc.event_id
        transaction_code = _text(txn, ["transactionCoding", "transactionCode"]).upper()
        acquired_disposed = _text(txn, ["transactionAmounts", "transactionAcquiredDisposedCode", "value"]).upper()
        transaction_date = _text(txn, ["transactionDate", "value"])
        shares = _to_float(_text(txn, ["transactionAmounts", "transactionShares", "value"]))
        price = _to_float(_text(txn, ["transactionAmounts", "transactionPricePerShare", "value"]))
        ownership_after = _to_float(_text(txn, ["postTransactionAmounts", "sharesOwnedFollowingTransaction", "value"]))
        direct_indirect = _text(txn, ["ownershipNature", "directOrIndirectOwnership", "value"])
        footnote_text = _transaction_footnotes(txn, footnotes, remarks)
        planned = _has_10b5_1(footnote_text)
        transaction_value = shares * price if pd.notna(shares) and pd.notna(price) else np.nan
        event_type, flags = _classify_transaction(
            transaction_code=transaction_code,
            acquired_disposed=acquired_disposed,
            derivative_flag=derivative_flag,
            shares=shares,
            price=price,
            planned=planned,
            owner=owner,
        )
        evidence = _norm_space(
            f"Form {form_type or '4'} {ticker}: owner={owner.get('reporting_owner_name', '')}; "
            f"code={transaction_code}; date={transaction_date}; shares={shares}; price={price}; {footnote_text}"
        )
        confidence = 0.94 if transaction_code else 0.65
        fact_values = {
            "insider_purchase_event_type": (event_type, "category"),
            "transaction_code": (transaction_code, "category"),
            "transaction_date": (transaction_date, "date"),
            "filing_acceptance_time": (doc.event_time.isoformat(), "timestamp"),
            "reporting_owner_name": (_norm(owner.get("reporting_owner_name")), "text"),
            "reporting_owner_role": (_norm(owner.get("reporting_owner_role")), "category"),
            "officer_title": (_norm(owner.get("officer_title")), "text"),
            "direct_or_indirect": (direct_indirect, "category"),
            "shares": (shares, "shares"),
            "price": (price, "usd_per_share"),
            "transaction_value": (transaction_value, "usd"),
            "ownership_after": (ownership_after, "shares"),
            "10b5_1_language": (planned, "boolean"),
            "derivative_flag": (derivative_flag, "boolean"),
            "footnote_text": (footnote_text, "text"),
            "open_market_purchase_flag": (event_type in PRIMARY_PURCHASE_TYPES, "boolean"),
            "officer_or_director_flag": (bool(owner.get("director_flag")) or bool(owner.get("officer_flag")), "boolean"),
            "ceo_purchase_flag": (event_type == "ceo_purchase", "boolean"),
            "cfo_purchase_flag": (event_type == "cfo_purchase", "boolean"),
            "director_purchase_flag": (event_type == "director_purchase", "boolean"),
            "ten_percent_owner_only_flag": (event_type == "ten_percent_owner_purchase", "boolean"),
            "hard_negative_flag": (event_type in HARD_NEGATIVE_TYPES, "boolean"),
            "amended_filing_flag": (amended, "boolean"),
            "parser_quality_flags": (";".join(flags), "text"),
        }
        for name, (value, unit) in fact_values.items():
            facts.append(_fact(doc, event_id, name, value, unit, evidence, confidence, "form4_xml"))
    return facts


def _fact_selection_priority(row: pd.Series) -> int:
    name = str(row.get("fact_name", ""))
    return 2 if name in {"insider_purchase_event_type", "transaction_value", "transaction_code"} else 1


def pivot_insider_purchase_facts(
    facts: pd.DataFrame,
    out_path: str | Path | None = None,
    *,
    min_confidence: float = 0.70,
) -> pd.DataFrame:
    if facts.empty:
        out = pd.DataFrame(columns=INSIDER_FEATURE_COLUMNS)
    else:
        usable = facts[pd.to_numeric(facts["confidence"], errors="coerce") >= float(min_confidence)].copy()
        rows: list[dict[str, object]] = []
        for event_id, group in usable.groupby("event_id", sort=False):
            ranked = group.copy()
            ranked["_selection_priority"] = ranked.apply(_fact_selection_priority, axis=1)
            first = ranked.iloc[0]
            row: dict[str, object] = {
                "event_id": event_id,
                "ticker": str(first.get("ticker", "")).upper(),
                "event_time": first.get("event_time", ""),
                "source_doc_ids": ";".join(sorted(ranked["source_doc_id"].astype(str).unique())),
                "usable_fact_count": int(len(ranked)),
                "source_type": first.get("source_type", ""),
                "source_url": first.get("source_url", ""),
                "source_evidence_text": first.get("evidence_text", ""),
            }
            for _, fact in ranked.sort_values(["confidence", "_selection_priority"], ascending=[False, False]).drop_duplicates("fact_name").iterrows():
                row[str(fact["fact_name"])] = fact["value"]
                row[f"{fact['fact_name']}_confidence"] = fact["confidence"]
            for col in INSIDER_FEATURE_COLUMNS:
                if col not in row:
                    row[col] = ""
            rows.append(row)
        out = pd.DataFrame(rows)
        if not out.empty:
            out["open_market_purchase_flag"] = out["open_market_purchase_flag"].map(_bool_value)
            out["hard_negative_flag"] = out["hard_negative_flag"].map(_bool_value)
            out["officer_or_director_flag"] = out["officer_or_director_flag"].map(_bool_value)
            out["amended_filing_flag"] = out["amended_filing_flag"].map(_bool_value)
    if out_path:
        ensure_parent(out_path)
        out.to_csv(out_path, index=False)
    return out


def insider_purchase_features_to_events(features: pd.DataFrame, out_path: str | Path) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, row in features.iterrows():
        event_type = _norm(row.get("insider_purchase_event_type"), default="non_open_market_transaction")
        ticker = _norm(row.get("ticker")).upper()
        transaction_value = _to_float(row.get("transaction_value", np.nan))
        magnitude = "unknown"
        if pd.notna(transaction_value):
            magnitude = "high" if transaction_value >= 1_000_000 else "medium" if transaction_value >= 100_000 else "low"
        primary = _bool_value(row.get("open_market_purchase_flag"))
        rows.append(
            {
                "event_id": row["event_id"],
                "ticker": ticker,
                "event_time": row["event_time"],
                "event_type": "insider_transaction",
                "summary": f"{ticker} Form 4 {event_type.replace('_', ' ')} candidate.",
                "event_subtype": event_type,
                "event_family": INSIDER_PURCHASE_DOMAIN,
                "source_type": row.get("source_type", "sec_form4_xml"),
                "source_url": row.get("source_url", ""),
                "release_session": "unknown",
                "expectedness": "unknown",
                "surprise_direction": "positive" if primary else "neutral",
                "surprise_magnitude": magnitude,
                "materiality": 0.65 if primary and magnitude in {"medium", "high"} else 0.25,
                "sector_benchmark": "",
                "notes": "Form 4 parser candidate; review open-market code, role, 10b5-1 language, duplicates/amendments, market-cap context, and prior purchases before modeling.",
                "review_status": "unreviewed",
                "label_quality": "machine_candidate",
                "source_doc_ids": row.get("source_doc_ids", ""),
                "evidence_status": "source_backed",
                "execution_survivability_class": "delayed-digestion" if primary else "explanation-only",
                "first_realistic_entry": "next_open_after_sec_acceptance",
                "tradeability_after_first_entry_rationale": "Form 4 disclosures are public only after SEC acceptance; any tradable hypothesis must survive next-open execution and cost stress, not only close-to-close explanation.",
                "next_open_required_flag": True,
                "close_to_close_explanatory_only_flag": True,
                "execution_survivability_gate": "not_evaluated",
                "execution_cost_stress_required": "25bps;50bps;100bps",
                **{c: row.get(c, "") for c in features.columns if c not in {"ticker", "event_id", "event_time", "source_type", "source_url", "source_doc_ids"}},
            }
        )
    make_event_template(out_path, rows)
    return pd.DataFrame(rows)


def parse_insider_purchase_manifest(
    documents_path: str | Path,
    facts_out: str | Path,
    features_out: str | Path,
    events_out: str | Path,
    *,
    min_confidence: float = 0.0,
    usable_confidence: float = 0.70,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    docs = load_source_documents(documents_path)
    rows: list[dict[str, object]] = []
    for doc in docs:
        for fact in parse_insider_purchase_document(doc):
            if fact.confidence >= min_confidence:
                rows.append(fact.to_dict())
    facts = pd.DataFrame(rows, columns=INSIDER_FACT_COLUMNS)
    if not facts.empty:
        facts = facts.sort_values(["ticker", "event_time", "event_id", "fact_name"]).reset_index(drop=True)
    ensure_parent(facts_out)
    facts.to_csv(facts_out, index=False)
    features = pivot_insider_purchase_facts(facts, features_out, min_confidence=usable_confidence)
    events = insider_purchase_features_to_events(features, events_out)
    return facts, features, events


def build_insider_purchase_sec_source_documents(
    client: SecClient,
    tickers: list[str],
    out_manifest: str | Path,
    docs_dir: str | Path,
    *,
    start: str | None = "2018-01-01",
    end: str | None = None,
    forms: list[str] | None = None,
    limit_per_ticker: int | None = None,
    sector_benchmark: str = "",
    overwrite: bool = False,
    min_text_chars: int = 80,
) -> tuple[pd.DataFrame, IngestionDiagnostics]:
    forms = [f.upper().strip() for f in (forms or ["4", "4/A"]) if str(f).strip()]
    df, diag = build_sec_source_document_manifest(
        client,
        tickers=tickers,
        out_manifest=out_manifest,
        docs_dir=docs_dir,
        forms=forms,
        start=start,
        end=end,
        item_filter=None,
        limit_per_ticker=limit_per_ticker,
        include_primary=True,
        include_exhibits=False,
        exhibit_pattern=r"(?i)\.xml$|form4|ownership",
        sector_benchmark=sector_benchmark,
        overwrite=overwrite,
        min_text_chars=min_text_chars,
    )
    if not df.empty:
        df = df.copy()
        df["event_type"] = "insider_transaction"
        df["event_subtype"] = "sec_form4_xml"
        df["source_type"] = "sec_form4_xml"
        df["notes"] = df.get("notes", pd.Series("", index=df.index)).fillna("").astype(str) + " insider_purchase_clusters_candidate=true"
        df.to_csv(out_manifest, index=False)
    return df, diag


def validate_insider_purchase_parser(
    facts: pd.DataFrame,
    gold: pd.DataFrame,
    *,
    out_errors: str | Path | None = None,
    tolerance_default: float = 1e-6,
) -> tuple[pd.DataFrame, dict[str, object]]:
    fact_map = {(str(r["event_id"]), str(r["fact_name"])): r for _, r in facts.iterrows()} if not facts.empty else {}
    rows: list[dict[str, object]] = []
    for _, expected in gold.iterrows():
        key = (str(expected.get("event_id")), str(expected.get("fact_name")))
        actual = fact_map.get(key)
        expected_present = _bool_value(expected.get("expected_present", True))
        expected_value = expected.get("expected_value", "")
        tolerance = _to_float(expected.get("tolerance", tolerance_default))
        if pd.isna(tolerance):
            tolerance = tolerance_default
        if actual is None:
            status = "ok" if not expected_present else "missing"
            actual_value = ""
        else:
            actual_value = actual.get("value", "")
            if not expected_present:
                status = "ok" if _norm(actual_value).lower() in {"", "unknown", "false", "0"} else "false_positive"
            else:
                exp_num = _to_float(expected_value)
                act_num = _to_float(actual_value)
                if pd.notna(exp_num) and pd.notna(act_num):
                    status = "ok" if abs(exp_num - act_num) <= tolerance else "mismatch"
                elif str(expected_value).strip().lower() == str(actual_value).strip().lower():
                    status = "ok"
                else:
                    status = "mismatch"
        rows.append(
            {
                "event_id": key[0],
                "fact_name": key[1],
                "expected_value": expected_value,
                "actual_value": actual_value,
                "expected_present": expected_present,
                "gold_category": expected.get("gold_category", ""),
                "status": status,
            }
        )
    errors = pd.DataFrame(rows)
    by_fact = {}
    for fact_name, group in errors.groupby("fact_name") if not errors.empty else []:
        by_fact[fact_name] = {
            "gold_rows": int(len(group)),
            "correct": int((group["status"] == "ok").sum()),
            "accuracy": float((group["status"] == "ok").mean()) if len(group) else 0.0,
        }
    report = {
        "gold_rows": int(len(errors)),
        "correct_rows": int((errors.get("status", pd.Series(dtype=str)) == "ok").sum()) if not errors.empty else 0,
        "row_accuracy": float((errors.get("status", pd.Series(dtype=str)) == "ok").mean()) if len(errors) else 0.0,
        "by_fact": by_fact,
    }
    false_positive_types = errors.loc[errors["status"].eq("false_positive"), "gold_category"].fillna("").astype(str).str.lower() if not errors.empty else pd.Series(dtype=str)
    gates = {
        "gold_set_60_rows": report["gold_rows"] >= 60,
        "row_accuracy_90": report["row_accuracy"] >= 0.90,
        "no_option_exercise_false_purchase": "option_exercise" not in set(false_positive_types),
        "no_tax_withholding_false_purchase": "tax_withholding" not in set(false_positive_types),
        "no_planned_transaction_false_purchase": "planned_transaction" not in set(false_positive_types),
        "no_non_open_market_false_purchase": "non_open_market_transaction" not in set(false_positive_types),
    }
    report["audit_gate_results"] = gates
    report["parser_audit_pass"] = bool(all(gates.values()))
    if out_errors:
        ensure_parent(out_errors)
        errors.to_csv(out_errors, index=False)
    return errors, report


def _load_optional_context(path: str | Path | None) -> pd.DataFrame:
    if not path:
        return pd.DataFrame()
    p = Path(path)
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def _lookup_context(row: pd.Series, context: pd.DataFrame) -> pd.Series:
    if context.empty:
        return pd.Series(dtype=object)
    event_id = _norm(row.get("event_id"))
    if "event_id" in context.columns:
        matched = context[context["event_id"].astype(str) == event_id]
        if not matched.empty:
            return matched.iloc[0]
    if "ticker" not in context.columns:
        return pd.Series(dtype=object)
    subset = context[context["ticker"].astype(str).str.upper() == _norm(row.get("ticker")).upper()].copy()
    if subset.empty:
        return pd.Series(dtype=object)
    sort_col = "filed_at" if "filed_at" in subset.columns else "asof_date" if "asof_date" in subset.columns else ""
    if sort_col:
        subset[sort_col] = pd.to_datetime(subset[sort_col], errors="coerce").dt.tz_localize(None)
        event_time = pd.to_datetime(row.get("event_time"), errors="coerce")
        if pd.notna(event_time):
            event_time = event_time.tz_localize(None) if getattr(event_time, "tzinfo", None) else event_time
            subset = subset[subset[sort_col] <= event_time]
        subset = subset.sort_values(sort_col, ascending=False)
    return subset.iloc[0] if not subset.empty else pd.Series(dtype=object)


def _anchor_price(prices: pd.DataFrame, event_time: object, release_session: object) -> tuple[pd.Timestamp | None, float]:
    ts = pd.to_datetime(event_time, errors="coerce")
    if pd.isna(ts):
        return None, np.nan
    ts = ts.tz_localize(None) if getattr(ts, "tzinfo", None) else ts
    date = ts.normalize()
    session = _norm(release_session).lower()
    eligible = prices[prices["date"] <= date] if session in {"after_close", "intraday", "unknown", ""} else prices[prices["date"] < date]
    if eligible.empty:
        return None, np.nan
    last = eligible.iloc[-1]
    return pd.to_datetime(last["date"]), _to_float(last["adj_close"])


def _window_return(prices: pd.DataFrame, anchor_date: pd.Timestamp | None, window: int) -> float:
    if anchor_date is None or prices.empty:
        return np.nan
    idx_matches = prices.index[prices["date"] == anchor_date].tolist()
    if not idx_matches:
        return np.nan
    idx = idx_matches[-1]
    start_idx = idx - int(window)
    if start_idx < 0:
        return np.nan
    start = _to_float(prices.iloc[start_idx]["adj_close"])
    end = _to_float(prices.iloc[idx]["adj_close"])
    return end / start - 1.0 if pd.notna(start) and pd.notna(end) and start else np.nan


def _distance_from_52w_high(prices: pd.DataFrame, anchor_date: pd.Timestamp | None) -> float:
    if anchor_date is None or prices.empty:
        return np.nan
    idx_matches = prices.index[prices["date"] == anchor_date].tolist()
    if not idx_matches:
        return np.nan
    idx = idx_matches[-1]
    start_idx = max(0, idx - 252)
    high = pd.to_numeric(prices.iloc[start_idx : idx + 1]["adj_close"], errors="coerce").max()
    end = _to_float(prices.iloc[idx]["adj_close"])
    return end / high - 1.0 if pd.notna(high) and high else np.nan


def _avg_dollar_volume(prices: pd.DataFrame, anchor_date: pd.Timestamp | None, window: int = 20) -> float:
    if anchor_date is None or prices.empty:
        return np.nan
    idx_matches = prices.index[prices["date"] == anchor_date].tolist()
    if not idx_matches:
        return np.nan
    idx = idx_matches[-1]
    start_idx = max(0, idx - window + 1)
    frame = prices.iloc[start_idx : idx + 1]
    if not {"adj_close", "volume"}.issubset(frame.columns):
        return np.nan
    return float((pd.to_numeric(frame["adj_close"], errors="coerce") * pd.to_numeric(frame["volume"], errors="coerce")).mean())


def enrich_insider_purchase_context(
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
    try:
        benchmark_prices = load_price_csv(prices_dir, benchmark_ticker.upper())
    except FileNotFoundError:
        benchmark_prices = pd.DataFrame()

    work = events.copy()
    work["_event_time_ts"] = pd.to_datetime(work.get("event_time"), errors="coerce").dt.tz_localize(None)
    primary = work.get("open_market_purchase_flag", pd.Series(False, index=work.index)).map(_bool_value)
    enriched_rows: list[dict[str, object]] = []
    for idx, row in work.iterrows():
        out = row.drop(labels=[c for c in ["_event_time_ts"] if c in row.index]).to_dict()
        ticker = _norm(row.get("ticker")).upper()
        status: list[str] = []
        try:
            prices = price_cache.setdefault(ticker, load_price_csv(prices_dir, ticker)) if ticker else pd.DataFrame()
        except FileNotFoundError:
            prices = pd.DataFrame()
            status.append("missing_ticker_prices")
        if benchmark_prices.empty:
            status.append("missing_benchmark_prices")
        anchor_date, last_close = _anchor_price(prices, row.get("event_time"), row.get("release_session")) if not prices.empty else (None, np.nan)
        out["price_anchor_date"] = anchor_date.date().isoformat() if anchor_date is not None else ""
        out["last_close_before_event"] = last_close

        shares_lookup = _lookup_context(row, shares_context)
        shares_outstanding = _to_float(row.get("shares_outstanding_before_event", np.nan))
        if pd.isna(shares_outstanding) and not shares_lookup.empty:
            shares_outstanding = _to_float(shares_lookup.get("shares_outstanding_before_event", np.nan))
        out["shares_outstanding_before_event"] = shares_outstanding

        market_lookup = _lookup_context(row, market_caps)
        market_cap = _to_float(row.get("market_cap_before_event", np.nan))
        if pd.isna(market_cap) and not market_lookup.empty:
            market_cap = _to_float(market_lookup.get("market_cap_before_event", np.nan))
        if pd.isna(market_cap) and pd.notna(shares_outstanding) and pd.notna(last_close):
            market_cap = shares_outstanding * last_close
        out["market_cap_before_event"] = market_cap

        transaction_value = _to_float(row.get("transaction_value", np.nan))
        shares = _to_float(row.get("shares", np.nan))
        out["transaction_value_pct_market_cap"] = transaction_value / market_cap if pd.notna(transaction_value) and pd.notna(market_cap) and market_cap else np.nan
        out["shares_purchased_pct_shares_outstanding"] = shares / shares_outstanding if pd.notna(shares) and pd.notna(shares_outstanding) and shares_outstanding else np.nan

        ts = row["_event_time_ts"]
        ticker_mask = work.get("ticker", pd.Series("", index=work.index)).fillna("").astype(str).str.upper().eq(ticker)
        known_primary = primary & ticker_mask & work["_event_time_ts"].notna() & (work["_event_time_ts"] <= ts)
        if pd.isna(ts):
            out["cluster_count_5d"] = 0
            out["cluster_count_10d"] = 0
            out["prior_6m_insider_purchase_count"] = 0
        else:
            owners = work.get("reporting_owner_name", pd.Series("", index=work.index)).fillna("").astype(str)
            for days in (5, 10):
                in_window = known_primary & (work["_event_time_ts"] >= ts - pd.Timedelta(days=days))
                out[f"cluster_count_{days}d"] = int(owners[in_window].replace("", np.nan).dropna().nunique() or int(in_window.sum()))
            prior = known_primary & (work["_event_time_ts"] < ts) & (work["_event_time_ts"] >= ts - pd.Timedelta(days=183))
            out["prior_6m_insider_purchase_count"] = int(prior.sum())
        out["purchase_cluster_flag"] = bool(out["cluster_count_10d"] >= 2 and _bool_value(row.get("open_market_purchase_flag")))
        out["cluster_signal_type"] = "purchase_cluster" if out["purchase_cluster_flag"] else _norm(row.get("insider_purchase_event_type"))
        if _bool_value(row.get("hard_negative_flag")):
            out["execution_survivability_class"] = "explanation-only"
            rationale = "Hard-negative Form 4 rows are controls or parser negatives, not tradable insider-purchase signals."
        elif out["purchase_cluster_flag"]:
            out["execution_survivability_class"] = "slow-burn repricing"
            rationale = "The cluster thesis is that repeated officer/director purchases update belief over several disclosures; it may remain tradeable after next open only if next-open stress confirms the effect."
        elif _bool_value(row.get("open_market_purchase_flag")):
            out["execution_survivability_class"] = "delayed-digestion"
            rationale = "A single Form 4 purchase is disclosed after the insider already traded; any edge must come from delayed market digestion of role, size, and context."
        else:
            out["execution_survivability_class"] = "explanation-only"
            rationale = "Non-primary Form 4 rows explain ownership changes but are not an open-market purchase signal."
        out["first_realistic_entry"] = "next_open_after_sec_acceptance"
        out["tradeability_after_first_entry_rationale"] = rationale
        out["next_open_required_flag"] = True
        out["close_to_close_explanatory_only_flag"] = True
        out["execution_survivability_gate"] = _norm(row.get("execution_survivability_gate"), default="not_evaluated")
        out["execution_cost_stress_required"] = "25bps;50bps;100bps"

        for window in (20, 60):
            stock_ret = _window_return(prices, anchor_date, window) if not prices.empty else np.nan
            bench_anchor, _ = _anchor_price(benchmark_prices, row.get("event_time"), row.get("release_session")) if not benchmark_prices.empty else (None, np.nan)
            bench_ret = _window_return(benchmark_prices, bench_anchor, window) if not benchmark_prices.empty else np.nan
            out[f"pre_event_return_{window}d"] = stock_ret
            out[f"pre_event_benchmark_return_{window}d"] = bench_ret
            out[f"pre_event_market_adjusted_return_{window}d"] = stock_ret - bench_ret if pd.notna(stock_ret) and pd.notna(bench_ret) else np.nan
        out["distance_from_52w_high"] = _distance_from_52w_high(prices, anchor_date)
        out["pre20_avg_dollar_volume"] = _avg_dollar_volume(prices, anchor_date)
        if pd.isna(market_cap):
            status.append("missing_market_cap")
        if pd.isna(shares_outstanding):
            status.append("missing_shares_outstanding")
        if pd.isna(out["pre_event_market_adjusted_return_20d"]):
            status.append("missing_pre_event_runup")
        out["insider_purchase_context_status"] = "ok" if not status else ";".join(sorted(set(status)))
        enriched_rows.append(out)

    enriched = pd.DataFrame(enriched_rows)
    ensure_parent(out_path)
    enriched.to_csv(out_path, index=False)
    return enriched


def build_insider_purchase_duplicate_audit(
    events: str | Path | pd.DataFrame,
    *,
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    df = pd.read_csv(events) if not isinstance(events, pd.DataFrame) else events.copy()
    if df.empty:
        out = pd.DataFrame()
        if out_path:
            ensure_parent(out_path)
            out.to_csv(out_path, index=False)
        return out
    key = (
        df.get("ticker", pd.Series("", index=df.index)).fillna("").astype(str).str.upper()
        + "|"
        + df.get("reporting_owner_name", pd.Series("", index=df.index)).fillna("").astype(str).str.lower()
        + "|"
        + df.get("transaction_date", pd.Series("", index=df.index)).fillna("").astype(str)
        + "|"
        + df.get("transaction_code", pd.Series("", index=df.index)).fillna("").astype(str).str.upper()
        + "|"
        + pd.to_numeric(df.get("shares", pd.Series(index=df.index, dtype=float)), errors="coerce").round(4).astype(str)
        + "|"
        + pd.to_numeric(df.get("price", pd.Series(index=df.index, dtype=float)), errors="coerce").round(4).astype(str)
    )
    counts = key.value_counts()
    amended = df.get("amended_filing_flag", pd.Series(False, index=df.index)).map(_bool_value)
    rows = []
    for i, row in df.iterrows():
        duplicate_count = int(counts.get(key.iloc[i], 0))
        duplicate_type = "none"
        risk = "low"
        if duplicate_count > 1 and amended.iloc[i]:
            duplicate_type = "amended_form4_duplicate"
            risk = "high"
        elif duplicate_count > 1:
            duplicate_type = "same_owner_transaction_duplicate"
            risk = "medium"
        rows.append(
            {
                "event_id": row.get("event_id", ""),
                "ticker": row.get("ticker", ""),
                "duplicate_key": key.iloc[i],
                "same_key_event_count": duplicate_count,
                "amended_filing_flag": bool(amended.iloc[i]),
                "duplicate_type": duplicate_type,
                "duplicate_risk_level": risk,
                "model_count_once_flag": duplicate_type == "none",
            }
        )
    out = pd.DataFrame(rows)
    if out_path:
        ensure_parent(out_path)
        out.to_csv(out_path, index=False)
    return out


def build_insider_purchase_timestamp_audit(
    events: str | Path | pd.DataFrame,
    *,
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    df = pd.read_csv(events) if not isinstance(events, pd.DataFrame) else events.copy()
    rows = []
    for _, row in df.iterrows():
        event_time = pd.to_datetime(row.get("event_time"), errors="coerce")
        transaction_date = pd.to_datetime(row.get("transaction_date"), errors="coerce")
        release_session = _norm(row.get("release_session"), default="unknown").lower()
        findings: list[str] = []
        risk = "low"
        if pd.isna(event_time):
            risk = "high"
            findings.append("missing_filing_acceptance_time")
        if pd.isna(transaction_date):
            risk = "medium" if risk == "low" else risk
            findings.append("missing_transaction_date")
        elif pd.notna(event_time) and event_time.normalize() < transaction_date.normalize():
            risk = "high"
            findings.append("filing_time_before_transaction_date")
        if release_session == "unknown":
            risk = "medium" if risk == "low" else risk
            findings.append("unknown_release_session")
        rows.append(
            {
                "event_id": row.get("event_id", ""),
                "ticker": row.get("ticker", ""),
                "transaction_date": "" if pd.isna(transaction_date) else transaction_date.date().isoformat(),
                "filing_acceptance_time": "" if pd.isna(event_time) else event_time.isoformat(),
                "release_session": release_session,
                "timestamp_risk_level": risk,
                "timestamp_findings": ";".join(findings) if findings else "none",
            }
        )
    out = pd.DataFrame(rows)
    if out_path:
        ensure_parent(out_path)
        out.to_csv(out_path, index=False)
    return out


def insider_purchase_readiness_summary(
    events: pd.DataFrame,
    *,
    source_documents: pd.DataFrame | None = None,
    parser_errors: pd.DataFrame | None = None,
    duplicate_audit: pd.DataFrame | None = None,
    timestamp_audit: pd.DataFrame | None = None,
    min_train: int = 40,
) -> dict[str, object]:
    source_rows = int(len(source_documents)) if source_documents is not None else int(events.get("source_doc_ids", pd.Series(dtype=str)).fillna("").astype(str).str.len().gt(0).sum())
    if events.empty:
        gates = {
            "reviewed_usable_events_80_min": False,
            "primary_open_market_purchase_events_60": False,
            "officer_or_director_purchase_events_40": False,
            "purchase_cluster_events_30": False,
            "transaction_value_pct_market_cap_rows_40": False,
            "pre_event_runup_rows_40": False,
            "clear_filing_timestamps": False,
            "duplicate_audit_pass": False,
            "execution_survivability_gate_pass": False,
            "parser_audit_pass": False,
            "likely_oos_predictions_30": False,
        }
        return {
            "source_documents_recovered": source_rows,
            "parsed_event_rows": 0,
            "reviewed_usable_rows": 0,
            "gates": gates,
            "top_missing_fields_blocking_modeling": list(gates),
            "decision": "continue corpus buildout",
            "reason": "no parsed event rows",
        }
    review_status = events.get("review_status", pd.Series([""] * len(events), index=events.index)).fillna("").astype(str).str.lower()
    usable = events[~review_status.isin({"rejected", "drop", "dropped"})].copy()
    reviewed = usable[usable.get("review_status", pd.Series([""] * len(usable), index=usable.index)).fillna("").astype(str).str.lower().isin({"reviewed", "curated", "approved"})].copy()
    primary = reviewed.get("open_market_purchase_flag", pd.Series(False, index=reviewed.index)).map(_bool_value)
    hard_negative = reviewed.get("hard_negative_flag", pd.Series(False, index=reviewed.index)).map(_bool_value)
    timestamps = pd.to_datetime(reviewed.get("event_time", pd.Series(index=reviewed.index, dtype=str)), errors="coerce")
    release_session = reviewed.get("release_session", pd.Series("", index=reviewed.index)).fillna("").astype(str).str.lower()
    clear_timestamps = timestamps.notna() & release_session.isin({"before_open", "intraday", "after_close"})
    metrics: dict[str, object] = {
        "source_documents_recovered": source_rows,
        "parsed_event_rows": int(len(events)),
        "reviewed_usable_rows": int(len(reviewed)),
        "primary_open_market_purchase_rows": int(primary.sum()),
        "hard_negative_rows": int(hard_negative.sum()),
        "officer_or_director_purchase_rows": int((primary & reviewed.get("officer_or_director_flag", pd.Series(False, index=reviewed.index)).map(_bool_value)).sum()),
        "ceo_cfo_purchase_rows": int((primary & (reviewed.get("ceo_purchase_flag", pd.Series(False, index=reviewed.index)).map(_bool_value) | reviewed.get("cfo_purchase_flag", pd.Series(False, index=reviewed.index)).map(_bool_value))).sum()),
        "purchase_cluster_10d_rows": int((primary & (pd.to_numeric(reviewed.get("cluster_count_10d", pd.Series(index=reviewed.index, dtype=float)), errors="coerce").fillna(0) >= 2)).sum()),
        "rows_with_transaction_value_pct_market_cap": int(pd.to_numeric(reviewed.get("transaction_value_pct_market_cap", pd.Series(index=reviewed.index, dtype=float)), errors="coerce").notna().sum()),
        "rows_with_pre_event_runup": int(pd.to_numeric(reviewed.get("pre_event_market_adjusted_return_20d", pd.Series(index=reviewed.index, dtype=float)), errors="coerce").notna().sum()),
        "rows_with_shares_outstanding_context": int(pd.to_numeric(reviewed.get("shares_outstanding_before_event", pd.Series(index=reviewed.index, dtype=float)), errors="coerce").notna().sum()),
        "rows_with_clear_filing_timestamps": int(clear_timestamps.sum()),
        "rows_with_execution_survivability_pass": int(reviewed.get("execution_survivability_gate", pd.Series("", index=reviewed.index)).fillna("").astype(str).str.lower().isin({"pass", "passed"}).sum()),
        "likely_oos_predictions_min_train": int(max(0, len(reviewed) - int(min_train))),
    }
    gates = {
        "reviewed_usable_events_80_min": metrics["reviewed_usable_rows"] >= 80,
        "primary_open_market_purchase_events_60": metrics["primary_open_market_purchase_rows"] >= 60,
        "officer_or_director_purchase_events_40": metrics["officer_or_director_purchase_rows"] >= 40,
        "purchase_cluster_events_30": metrics["purchase_cluster_10d_rows"] >= 30,
        "transaction_value_pct_market_cap_rows_40": metrics["rows_with_transaction_value_pct_market_cap"] >= 40,
        "pre_event_runup_rows_40": metrics["rows_with_pre_event_runup"] >= 40,
        "clear_filing_timestamps": metrics["rows_with_clear_filing_timestamps"] >= metrics["reviewed_usable_rows"] and metrics["reviewed_usable_rows"] > 0,
        "execution_survivability_gate_pass": metrics["rows_with_execution_survivability_pass"] >= metrics["reviewed_usable_rows"] and metrics["reviewed_usable_rows"] > 0,
        "likely_oos_predictions_30": metrics["likely_oos_predictions_min_train"] >= 30,
    }
    if parser_errors is not None:
        ok_count = int((parser_errors.get("status", pd.Series(dtype=str)) == "ok").sum()) if not parser_errors.empty else 0
        audit_rows = int(len(parser_errors))
        audit_accuracy = ok_count / audit_rows if audit_rows else 0.0
        metrics["parser_audit_rows"] = audit_rows
        metrics["parser_audit_accuracy"] = float(audit_accuracy)
        gates["parser_audit_pass"] = bool(audit_rows >= 60 and audit_accuracy >= 0.90)
    else:
        metrics["parser_audit_accuracy"] = "missing"
        gates["parser_audit_pass"] = False
    if duplicate_audit is not None:
        high_dup = int((duplicate_audit.get("duplicate_risk_level", pd.Series(dtype=str)) == "high").sum()) if not duplicate_audit.empty else 0
        metrics["high_risk_duplicate_rows"] = high_dup
        gates["duplicate_audit_pass"] = bool(high_dup == 0 and len(duplicate_audit) >= metrics["reviewed_usable_rows"])
    else:
        gates["duplicate_audit_pass"] = False
    if timestamp_audit is not None:
        high_ts = int((timestamp_audit.get("timestamp_risk_level", pd.Series(dtype=str)) == "high").sum()) if not timestamp_audit.empty else 0
        metrics["high_risk_timestamp_rows"] = high_ts
        gates["timestamp_audit_pass"] = bool(high_ts == 0 and len(timestamp_audit) >= metrics["reviewed_usable_rows"])
    else:
        gates["timestamp_audit_pass"] = False
    hard_gate_names = [gate for gate in gates]
    blockers = [gate for gate in hard_gate_names if not gates.get(gate)]
    metrics["gates"] = {gate: bool(passed) for gate, passed in gates.items()}
    metrics["top_missing_fields_blocking_modeling"] = blockers
    if not metrics["gates"]["parser_audit_pass"] and metrics["reviewed_usable_rows"] >= 40:
        metrics["decision"] = "parser not trusted"
        metrics["reason"] = "parser audit is missing or below gate"
    elif metrics["reviewed_usable_rows"] >= 80 and (
        not metrics["gates"]["transaction_value_pct_market_cap_rows_40"] or not metrics["gates"]["pre_event_runup_rows_40"]
    ):
        metrics["decision"] = "context insufficient"
        metrics["reason"] = "reviewed corpus size is plausible but market-cap/run-up context is incomplete"
    elif all(metrics["gates"].get(gate) for gate in hard_gate_names):
        metrics["decision"] = "model-ready"
        metrics["reason"] = "all non-modeling readiness gates pass"
    else:
        metrics["decision"] = "continue corpus buildout"
        metrics["reason"] = "readiness gates still failing: " + ", ".join(blockers)
    return metrics


def write_insider_purchase_readiness_report(
    events_path: str | Path,
    out_path: str | Path,
    *,
    source_documents_path: str | Path | None = None,
    parser_errors_path: str | Path | None = None,
    duplicate_audit_path: str | Path | None = None,
    timestamp_audit_path: str | Path | None = None,
    min_train: int = 40,
) -> dict[str, object]:
    events = pd.read_csv(events_path)
    source_documents = pd.read_csv(source_documents_path) if source_documents_path else None
    parser_errors = pd.read_csv(parser_errors_path) if parser_errors_path else None
    duplicate_audit = pd.read_csv(duplicate_audit_path) if duplicate_audit_path else None
    timestamp_audit = pd.read_csv(timestamp_audit_path) if timestamp_audit_path else None
    summary = insider_purchase_readiness_summary(
        events,
        source_documents=source_documents,
        parser_errors=parser_errors,
        duplicate_audit=duplicate_audit,
        timestamp_audit=timestamp_audit,
        min_train=min_train,
    )
    out = ensure_parent(out_path)
    lines = [
        "# Insider Purchase Clusters Readiness Report",
        "",
        "This is a data-readiness report, not a prediction result.",
        "",
        "## Verdict",
        "",
        f"- decision: {summary.get('decision')}",
        f"- reason: {summary.get('reason')}",
        "",
        "## Required Counts",
        "",
    ]
    for key, value in summary.items():
        if key in {"gates", "top_missing_fields_blocking_modeling", "decision", "reason"}:
            continue
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Gates", ""])
    for gate, passed in (summary.get("gates", {}) or {}).items():
        lines.append(f"- {gate}: {'PASS' if passed else 'FAIL'}")
    lines.extend(["", "## Top Missing Fields Blocking Modeling", ""])
    for blocker in summary.get("top_missing_fields_blocking_modeling", []) or []:
        lines.append(f"- {blocker}")
    lines.extend(
        [
            "",
            "## Execution Survivability Gate",
            "",
            "- required before modeling: PASS",
            "- domain classification: delayed-digestion / slow-burn repricing candidate for open-market clusters; explanation-only for hard negatives and non-market transactions.",
            "- first realistic entry: next open after SEC acceptance, or later if the filing appears after market close.",
            "- why it might remain tradeable: the thesis is delayed market digestion of role, size, repeat purchases, and company context rather than the insider's already-completed trade.",
            "- close-to-close rule: close-to-close abnormal return is explanatory only unless next-open behavior survives 25/50/100 bps cost stress.",
            "- current status: not passed unless every reviewed row has execution_survivability_gate = pass after close-to-close and next-open stress are both reported.",
            "",
            "## Pre-Registered Candidate Hypotheses",
            "",
            "1. Multiple open-market officer/director purchases within 10 days are positive.",
            "2. CEO/CFO purchases are stronger than director-only purchases.",
            "3. Larger transaction value relative to market cap is stronger.",
            "4. Purchases after drawdown or near a 52-week low differ from purchases after run-up.",
            "",
            "Do not model until every hard gate above passes. Do not tune thresholds after returns, and do not graduate this signal from one pass.",
        ]
    )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
