from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re

import numpy as np
import pandas as pd

from .events import make_event_template
from .paths import ensure_parent
from .prices import load_price_csv
from .sec import SecClient, _release_session_from_acceptance
from .source_docs import SourceDocument, load_source_documents


ACCOUNTING_INTEGRITY_DOMAIN = "accounting_integrity_8k"
ACCOUNTING_INTEGRITY_SEC_FORMS = ("8-K", "8-K/A")
ACCOUNTING_INTEGRITY_8K_ITEMS = ("4.01", "4.02")
ACCOUNTING_INTEGRITY_EXHIBIT_PATTERN = r"(?i)(ex[-_]?16|exhibit[-_ ]?16|dex16|16[._-]?1|letter)"

ACCOUNTING_INTEGRITY_EVENT_TYPES = {
    "non_reliance_financial_statements",
    "auditor_resignation",
    "auditor_dismissal",
    "auditor_disagreement",
    "reportable_event",
    "restatement_warning",
    "routine_auditor_change",
    "auditor_letter_disagreement",
    "accounting_error_correction",
    "internal_control_issue",
}

HIGH_SEVERITY_EVENT_TYPES = {
    "non_reliance_financial_statements",
    "auditor_resignation",
    "auditor_disagreement",
    "reportable_event",
    "auditor_letter_disagreement",
}

BIG4_PATTERNS = ("DELOITTE", "ERNST", "EY", "KPMG", "PRICEWATERHOUSE", "PWC")

NON_RELIANCE_RE = re.compile(
    r"(?:should\s+no\s+longer\s+be\s+relied\s+upon|should\s+not\s+be\s+relied\s+upon|"
    r"not\s+rely\s+on\s+(?:the\s+)?(?:previously\s+issued\s+)?financial\s+statements|"
    r"non[-\s]?reliance)",
    re.I,
)
ITEM_401_RE = re.compile(r"item\s+4\.01|changes\s+in\s+registrant(?:'s)?\s+certifying\s+accountant", re.I)
ITEM_402_RE = re.compile(r"item\s+4\.02|non[-\s]?reliance\s+on\s+previously\s+issued\s+financial\s+statements", re.I)
PERIOD_RE = re.compile(
    r"(?:year|quarter|period|fiscal\s+(?:year|quarter))s?\s+ended?\s+"
    r"(?P<period>[A-Z][a-z]+\s+\d{1,2},\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4}|(?:20|19)\d{2})",
    re.I,
)


@dataclass(frozen=True)
class AccountingIntegrityFact:
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


def _norm_space(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def _to_float(value: object) -> float:
    return float(pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0])


def _segments(text: str) -> list[str]:
    parts = []
    for raw in re.split(r"(?<!\d)[\.;!?](?!\d)|\n+", str(text or "")):
        seg = _norm_space(raw)
        if 10 <= len(seg) <= 900:
            parts.append(seg)
    return parts


def _fact(doc: SourceDocument, name: str, value: str | float | bool, unit: str, evidence: str, confidence: float, method: str) -> AccountingIntegrityFact:
    return AccountingIntegrityFact(
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


def _first_evidence(text: str, patterns: list[str]) -> str:
    for seg in _segments(text):
        low = seg.lower()
        if any(p in low for p in patterns):
            return seg
    return ""


def _extract_auditor_name(text: str, *, prior: bool) -> str:
    patterns = [
        r"(?:dismissed|resigned|declined\s+to\s+stand\s+for\s+re-appointment|notified)\s+(?P<name>[A-Z][A-Za-z&.,\s]+?)(?:\s+as|\s*,|\s+that|\s+effective)",
        r"(?:engaged|appointed|approved\s+the\s+engagement\s+of)\s+(?P<name>[A-Z][A-Za-z&.,\s]+?)(?:\s+as|\s*,|\s+effective)",
    ]
    use = patterns[0] if prior else patterns[1]
    match = re.search(use, text, flags=re.I)
    if not match:
        return ""
    name = _norm_space(match.group("name"))
    return re.sub(r"\s+(?:the|its|our)$", "", name, flags=re.I).strip(" ,.")


def _infer_items(text: str, explicit_items: str = "") -> str:
    items = {item.strip() for item in str(explicit_items or "").split(",") if item.strip() in ACCOUNTING_INTEGRITY_8K_ITEMS}
    if ITEM_401_RE.search(text):
        items.add("4.01")
    if ITEM_402_RE.search(text) or NON_RELIANCE_RE.search(text):
        items.add("4.02")
    return ",".join(sorted(items))


def infer_accounting_integrity_event_type(text: str, explicit_items: str = "") -> tuple[str, str, float]:
    doc = _norm_space(text)
    low = doc.lower()
    item_numbers = _infer_items(doc, explicit_items)
    no_disagreement = bool(re.search(r"no\s+disagreements?|not\s+had\s+any\s+disagreements?|there\s+were\s+no\s+disagreements?", low))
    if NON_RELIANCE_RE.search(doc) or "4.02" in item_numbers:
        evidence = _first_evidence(doc, ["should no longer be relied", "should not be relied", "non-reliance", "non reliance", "restatement"])
        return "non_reliance_financial_statements", evidence or "Item 4.02/non-reliance language", 0.92
    if "disagree" in low and not no_disagreement and ("auditor" in low or "accountant" in low or "exhibit 16" in low):
        evidence = _first_evidence(doc, ["disagree", "disagreement"])
        return "auditor_disagreement", evidence or "auditor disagreement language", 0.88
    if "reportable event" in low or "reportable events" in low:
        evidence = _first_evidence(doc, ["reportable event"])
        return "reportable_event", evidence or "reportable event language", 0.86
    if "resign" in low or "declined to stand for re-appointment" in low or "declined to stand for reappointment" in low:
        evidence = _first_evidence(doc, ["resign", "declined to stand"])
        return "auditor_resignation", evidence or "auditor resignation language", 0.86
    if "material weakness" in low or "internal control" in low:
        evidence = _first_evidence(doc, ["material weakness", "internal control"])
        if "restat" in low or "error" in low:
            return "accounting_error_correction", evidence or "accounting error/internal control language", 0.78
        return "internal_control_issue", evidence or "internal control language", 0.72
    if "restat" in low:
        evidence = _first_evidence(doc, ["restat"])
        return "restatement_warning", evidence or "restatement language", 0.78
    if "dismiss" in low or "engaged" in low or "appointed" in low or "4.01" in item_numbers:
        evidence = _first_evidence(doc, ["dismiss", "engaged", "appointed", "changes in registrant"])
        return "routine_auditor_change", evidence or "auditor change language without adverse accounting-integrity facts", 0.74
    return "routine_auditor_change", "", 0.35


def parse_accounting_integrity_document(doc: SourceDocument) -> list[AccountingIntegrityFact]:
    text = _norm_space(doc.text)
    explicit_items = _norm(getattr(doc, "item_numbers", ""))
    event_type, evidence, conf = infer_accounting_integrity_event_type(text, explicit_items)
    low = text.lower()
    facts: list[AccountingIntegrityFact] = [
        _fact(doc, "accounting_integrity_event_type", event_type, "category", evidence, conf, "document_keyword"),
        _fact(doc, "item_number", _infer_items(text, explicit_items), "text", evidence, 0.84 if _infer_items(text, explicit_items) else 0.40, "item_keyword"),
    ]

    non_reliance = bool(NON_RELIANCE_RE.search(text) or event_type == "non_reliance_financial_statements")
    disagreement = "disagree" in low or "disagreement" in low
    reportable = "reportable event" in low or "reportable events" in low
    resignation = "resign" in low or "declined to stand for re-appointment" in low or "declined to stand for reappointment" in low
    dismissal = "dismiss" in low or "terminated" in low
    no_disagreement = bool(re.search(r"no\s+disagreements?|not\s+had\s+any\s+disagreements?|there\s+were\s+no\s+disagreements?", low))
    internal_control = "internal control" in low or "material weakness" in low
    auditor_letter = bool(re.search(r"exhibit\s+16|letter\s+from\s+(?:the\s+)?(?:former\s+)?(?:independent\s+)?(?:registered\s+)?(?:public\s+)?account", low))
    auditor_letter_agrees = auditor_letter and bool(re.search(r"\bagrees?\s+with\s+the\s+statements|\bagree\s+with\s+the\s+statements", low)) and "disagree" not in low
    auditor_letter_disagrees = auditor_letter and disagreement and not auditor_letter_agrees

    flags = {
        "non_reliance_flag": non_reliance,
        "disagreement_flag": disagreement and not no_disagreement,
        "reportable_event_flag": reportable,
        "internal_control_language": internal_control,
        "auditor_letter_present": auditor_letter,
        "auditor_letter_agrees": auditor_letter_agrees,
    }
    for name, value in flags.items():
        facts.append(_fact(doc, name, value, "boolean", evidence, 0.82, "document_keyword"))

    if resignation:
        change_type = "resignation"
    elif dismissal:
        change_type = "dismissal"
    elif "engaged" in low or "appointed" in low:
        change_type = "appointment"
    else:
        change_type = "none"
    facts.append(_fact(doc, "auditor_change_type", change_type, "category", evidence, 0.80, "auditor_change_keyword"))

    prior = _extract_auditor_name(text, prior=True)
    new = _extract_auditor_name(text, prior=False)
    if prior:
        facts.append(_fact(doc, "prior_auditor", prior, "text", prior, 0.68, "auditor_name_regex"))
    if new:
        facts.append(_fact(doc, "new_auditor", new, "text", new, 0.68, "auditor_name_regex"))

    periods = sorted({m.group("period") for m in PERIOD_RE.finditer(text)})
    if periods:
        facts.append(_fact(doc, "affected_periods", ";".join(periods), "text", "; ".join(periods), 0.66, "period_regex"))

    reason_evidence = _first_evidence(text, ["error", "restatement", "material weakness", "internal control", "revenue recognition", "tax", "inventory"])
    if reason_evidence:
        facts.append(_fact(doc, "restatement_reason", reason_evidence[:400], "text", reason_evidence, 0.64, "reason_sentence"))

    hard_negative = (
        (event_type == "routine_auditor_change" and no_disagreement)
        or "not related to any disagreement" in low
        or "merger of accounting firms" in low
        or "firm merger" in low
        or ("amended" in low and not non_reliance)
    )
    if auditor_letter_disagrees:
        facts.append(_fact(doc, "accounting_integrity_event_type", "auditor_letter_disagreement", "category", evidence, 0.90, "auditor_letter_keyword"))
    facts.append(_fact(doc, "hard_negative_flag", hard_negative, "boolean", evidence, 0.78, "hard_negative_keyword"))
    severity = "high" if event_type in HIGH_SEVERITY_EVENT_TYPES or auditor_letter_disagrees else "low" if hard_negative or event_type == "routine_auditor_change" else "medium"
    facts.append(_fact(doc, "severity_pre_price", severity, "category", evidence, 0.82, "severity_rules"))
    return facts


def _select_facts(facts: pd.DataFrame) -> pd.DataFrame:
    if facts.empty:
        return facts
    ordered = facts.copy()
    ordered["confidence"] = pd.to_numeric(ordered["confidence"], errors="coerce").fillna(0.0)
    ordered = ordered.sort_values(["event_id", "fact_name", "confidence"], ascending=[True, True, False])
    return ordered.drop_duplicates(["event_id", "fact_name"], keep="first")


def _feature_rows_from_facts(facts: pd.DataFrame, docs: list[SourceDocument]) -> pd.DataFrame:
    selected = _select_facts(facts)
    rows = []
    doc_by_event = {doc.event_id: doc for doc in docs}
    for event_id, group in selected.groupby("event_id"):
        doc = doc_by_event[event_id]
        values = {str(r["fact_name"]): r["value"] for _, r in group.iterrows()}
        evidence = {str(r["fact_name"]): r.get("evidence_text", "") for _, r in group.iterrows()}
        event_type = _norm(values.get("accounting_integrity_event_type"), "routine_auditor_change")
        severity = _norm(values.get("severity_pre_price"), "low")
        row = {
            "event_id": event_id,
            "ticker": doc.ticker,
            "event_time": doc.event_time.isoformat(),
            "release_session": doc.release_session,
            "source_type": doc.source_type,
            "source_url": doc.source_url,
            "source_doc_ids": doc.source_doc_id,
            "accounting_integrity_event_type": event_type,
            "item_number": _norm(values.get("item_number")),
            "non_reliance_flag": _bool_value(values.get("non_reliance_flag")),
            "affected_periods": _norm(values.get("affected_periods")),
            "restatement_reason": _norm(values.get("restatement_reason")),
            "auditor_change_type": _norm(values.get("auditor_change_type"), "none"),
            "prior_auditor": _norm(values.get("prior_auditor")),
            "new_auditor": _norm(values.get("new_auditor")),
            "disagreement_flag": _bool_value(values.get("disagreement_flag")),
            "reportable_event_flag": _bool_value(values.get("reportable_event_flag")),
            "internal_control_language": _bool_value(values.get("internal_control_language")),
            "auditor_letter_present": _bool_value(values.get("auditor_letter_present")),
            "auditor_letter_agrees": _bool_value(values.get("auditor_letter_agrees")),
            "hard_negative_flag": _bool_value(values.get("hard_negative_flag")),
            "severity_pre_price": severity,
            "evidence": _norm(evidence.get("accounting_integrity_event_type")),
            "confidence": float(pd.to_numeric(group["confidence"], errors="coerce").max()),
        }
        row.update(classify_accounting_integrity_execution_survivability(row))
        rows.append(row)
    return pd.DataFrame(rows)


def parse_accounting_integrity_manifest(
    documents_path: str | Path,
    facts_out: str | Path,
    features_out: str | Path,
    events_out: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    docs = load_source_documents(documents_path)
    all_facts = [fact.to_dict() for doc in docs for fact in parse_accounting_integrity_document(doc)]
    facts = pd.DataFrame(all_facts)
    features = _feature_rows_from_facts(facts, docs)
    ensure_parent(facts_out)
    facts.to_csv(facts_out, index=False)
    ensure_parent(features_out)
    features.to_csv(features_out, index=False)

    event_rows = []
    for _, row in features.iterrows():
        high = str(row.get("severity_pre_price", "")).lower() == "high"
        event_rows.append(
            {
                "event_id": row["event_id"],
                "ticker": row["ticker"],
                "event_time": row["event_time"],
                "event_type": "accounting_integrity",
                "summary": f"{row['ticker']} 8-K accounting integrity event: {row['accounting_integrity_event_type']}",
                "event_subtype": row["accounting_integrity_event_type"],
                "event_family": ACCOUNTING_INTEGRITY_DOMAIN,
                "source_type": row["source_type"],
                "source_url": row["source_url"],
                "release_session": row["release_session"],
                "expectedness": "surprise" if high else "unknown",
                "surprise_direction": "negative" if high else "neutral",
                "surprise_magnitude": "high" if high else "low",
                "materiality": 0.85 if high else 0.25,
                "sector_benchmark": "",
                "notes": "Generated from SEC 8-K Item 4.01/4.02 parser. Human review required before modeling.",
                "corpus_name": ACCOUNTING_INTEGRITY_DOMAIN,
                "review_status": "unreviewed",
                "label_quality": "unreviewed",
                "source_doc_ids": row["source_doc_ids"],
                "evidence_status": "source_backed",
                **{col: row.get(col) for col in features.columns if col not in {"event_id", "ticker", "event_time", "release_session", "source_type", "source_url", "source_doc_ids"}},
            }
        )
    make_event_template(events_out, event_rows)
    events = pd.read_csv(events_out)
    return facts, features, events


def build_accounting_integrity_sec_source_documents(
    client: SecClient,
    tickers: list[str],
    out_path: str | Path,
    *,
    start_date: str = "2015-01-01",
    limit_per_ticker: int | None = None,
    fetch_text: bool = False,
) -> tuple[pd.DataFrame, dict[str, object]]:
    rows = []
    diagnostics = {"tickers_total": len(tickers), "filings_seen": 0, "candidate_filings": 0, "documents_fetched": 0, "skipped": {}}

    def skip(reason: str) -> None:
        skipped = diagnostics["skipped"]
        skipped[reason] = int(skipped.get(reason, 0)) + 1

    for ticker in tickers:
        try:
            filings = client.recent_filings(ticker, forms=ACCOUNTING_INTEGRITY_SEC_FORMS)
        except Exception as exc:  # pragma: no cover - network/SEC availability varies
            skip(f"{ticker}: {type(exc).__name__}")
            continue
        if filings.empty:
            continue
        filings["filingDate"] = pd.to_datetime(filings["filingDate"], errors="coerce")
        filings = filings[filings["filingDate"] >= pd.Timestamp(start_date)]
        diagnostics["filings_seen"] = int(diagnostics["filings_seen"]) + int(len(filings))
        if "items" in filings.columns:
            item_text = filings["items"].fillna("").astype(str)
            filings = filings[item_text.str.contains(r"\b4\.01\b|\b4\.02\b", regex=True)].copy()
        else:
            filings = filings.iloc[0:0].copy()
        if limit_per_ticker is not None:
            filings = filings.head(int(limit_per_ticker))
        diagnostics["candidate_filings"] = int(diagnostics["candidate_filings"]) + int(len(filings))
        for _, filing in filings.iterrows():
            cik = int(filing["cik"])
            accession = str(filing["accessionNumber"])
            primary = _norm(filing.get("primaryDocument"))
            accepted = _norm(filing.get("acceptanceDateTime"), _norm(filing.get("filingDate")))
            event_time = pd.to_datetime(accepted, errors="coerce")
            if pd.isna(event_time):
                event_time = pd.to_datetime(filing.get("filingDate"), errors="coerce")
            source_url = client.filing_document_url(cik, accession, primary) if primary else SecClient.filing_base_url(cik, accession)
            text = ""
            if fetch_text and primary:
                try:
                    text, _ = client.fetch_document_text(source_url)
                    diagnostics["documents_fetched"] = int(diagnostics["documents_fetched"]) + 1
                except Exception as exc:  # pragma: no cover
                    skip(f"{ticker} {accession}: fetch {type(exc).__name__}")
            rows.append(
                {
                    "source_doc_id": f"{ticker}_{accession.replace('-', '')}",
                    "ticker": ticker.upper(),
                    "event_id": f"{ticker.upper()}_8K_{pd.Timestamp(event_time).date().isoformat()}_{accession}",
                    "event_time": pd.Timestamp(event_time).isoformat(),
                    "event_type": "accounting_integrity",
                    "event_subtype": "sec_8k_item_4",
                    "release_session": _release_session_from_acceptance(accepted),
                    "source_type": "sec_8k",
                    "source_url": source_url,
                    "title": f"{ticker.upper()} 8-K {accession}",
                    "path": "",
                    "text": text,
                    "fiscal_period_end": "",
                    "sector_benchmark": "",
                    "notes": "SEC submissions API candidate with Item 4.01/4.02; fetch_text=False leaves row as source discovery queue.",
                    "accession_number": accession,
                    "cik": cik,
                    "item_numbers": _norm(filing.get("items")),
                    "filing_date": pd.Timestamp(filing["filingDate"]).date().isoformat() if pd.notna(filing["filingDate"]) else "",
                    "primary_document": primary,
                }
            )
    out = pd.DataFrame(rows)
    ensure_parent(out_path)
    out.to_csv(out_path, index=False)
    diagnostics["rows"] = int(len(out))
    return out, diagnostics


def build_accounting_integrity_parser_gold_template(features: pd.DataFrame, out_path: str | Path, *, target_events: int = 60) -> pd.DataFrame:
    fact_names = [
        "accounting_integrity_event_type",
        "item_number",
        "non_reliance_flag",
        "auditor_change_type",
        "disagreement_flag",
        "reportable_event_flag",
        "auditor_letter_present",
        "auditor_letter_agrees",
        "severity_pre_price",
    ]
    rows = []
    sample = features.head(int(target_events)).copy()
    for _, row in sample.iterrows():
        for fact_name in fact_names:
            rows.append(
                {
                    "event_id": row.get("event_id", ""),
                    "ticker": row.get("ticker", ""),
                    "fact_name": fact_name,
                    "expected_value": row.get(fact_name, ""),
                    "unit": "boolean" if str(fact_name).endswith("_flag") or fact_name in {"auditor_letter_present", "auditor_letter_agrees"} else "category",
                    "tolerance": "",
                    "gold_review_status": "needs_human_review",
                    "reviewer_notes": "",
                }
            )
    gold = pd.DataFrame(rows)
    ensure_parent(out_path)
    gold.to_csv(out_path, index=False)
    return gold


def validate_accounting_integrity_parser(
    facts: pd.DataFrame,
    gold: pd.DataFrame,
    *,
    out_errors: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    if gold.empty:
        errors = pd.DataFrame(columns=["event_id", "fact_name", "status"])
        report = {"gold_rows": 0, "correct_rows": 0, "row_accuracy": 0.0, "parser_audit_pass": False, "status": "empty_gold_set"}
        if out_errors:
            ensure_parent(out_errors)
            errors.to_csv(out_errors, index=False)
        return errors, report
    review_status = gold.get("gold_review_status", pd.Series([""] * len(gold), index=gold.index)).fillna("").astype(str).str.lower()
    if not review_status.isin({"reviewed", "approved", "curated"}).all():
        errors = gold.copy()
        errors["actual_value"] = ""
        errors["status"] = "gold_not_reviewed"
        report = {
            "gold_rows": int(len(gold)),
            "correct_rows": 0,
            "row_accuracy": 0.0,
            "parser_audit_pass": False,
            "status": "gold_set_requires_human_review",
            "audit_gate_results": {"gold_set_human_reviewed": False, "gold_rows_60": len(gold) >= 60},
        }
        if out_errors:
            ensure_parent(out_errors)
            errors.to_csv(out_errors, index=False)
        return errors, report

    selected = _select_facts(facts)
    lookup = {(str(r["event_id"]), str(r["fact_name"])): r for _, r in selected.iterrows()} if not selected.empty else {}
    rows = []
    for _, row in gold.iterrows():
        key = (str(row.get("event_id", "")), str(row.get("fact_name", "")))
        pred = lookup.get(key)
        expected = row.get("expected_value", "")
        actual = pred.get("value") if pred is not None else ""
        unit = str(row.get("unit", "text")).lower()
        if pred is None:
            status = "missing_fact"
        elif unit == "boolean":
            status = "ok" if _bool_value(actual) == _bool_value(expected) else "wrong_value"
        else:
            status = "ok" if _norm(actual).lower() == _norm(expected).lower() else "wrong_value"
        rows.append({**row.to_dict(), "actual_value": actual, "status": status, "confidence": pred.get("confidence") if pred is not None else np.nan})
    errors = pd.DataFrame(rows)
    metrics = {}
    for fact_name, group in errors.groupby("fact_name"):
        ok = int((group["status"] == "ok").sum())
        total = int(len(group))
        metrics[fact_name] = {"gold_rows": total, "correct": ok, "recall_on_gold": ok / total if total else 0.0}
    gates = {
        "gold_rows_60": int(len(errors)) >= 60,
        "gold_events_20": int(errors["event_id"].nunique()) >= 20,
        "row_accuracy_90": float((errors["status"] == "ok").mean()) >= 0.90 if len(errors) else False,
        "high_severity_fact_accuracy_90": all(metrics.get(k, {}).get("recall_on_gold", 0.0) >= 0.90 for k in ["accounting_integrity_event_type", "non_reliance_flag", "severity_pre_price"]),
    }
    report = {
        "gold_rows": int(len(errors)),
        "gold_events": int(errors["event_id"].nunique()) if not errors.empty else 0,
        "correct_rows": int((errors["status"] == "ok").sum()) if not errors.empty else 0,
        "row_accuracy": float((errors["status"] == "ok").mean()) if not errors.empty else 0.0,
        "by_fact": metrics,
        "audit_gate_results": gates,
        "parser_audit_pass": bool(all(gates.values())),
    }
    if out_errors:
        ensure_parent(out_errors)
        errors.to_csv(out_errors, index=False)
    return errors, report


def write_accounting_integrity_parser_audit_report(report: dict[str, object], errors: pd.DataFrame, out_path: str | Path) -> Path:
    out = ensure_parent(out_path)
    lines = [
        "# Accounting Integrity 8-K Parser Audit Report",
        "",
        "This validates parser facts against a human-reviewed gold set. It is not a return result.",
        "",
        "## Metrics",
        "",
        f"- gold_rows: {report.get('gold_rows', 0)}",
        f"- gold_events: {report.get('gold_events', 0)}",
        f"- correct_rows: {report.get('correct_rows', 0)}",
        f"- row_accuracy: {report.get('row_accuracy', 0):.3f}",
        f"- parser_audit_pass: {report.get('parser_audit_pass', False)}",
        "",
        "## Gates",
        "",
    ]
    for gate, passed in (report.get("audit_gate_results", {}) or {}).items():
        lines.append(f"- {gate}: {'PASS' if passed else 'FAIL'}")
    lines.extend(["", "## By Fact", ""])
    for fact_name, metrics in (report.get("by_fact", {}) or {}).items():
        lines.append(f"- {fact_name}: {metrics}")
    bad = errors[errors["status"] != "ok"] if not errors.empty and "status" in errors.columns else pd.DataFrame()
    if not bad.empty:
        lines.extend(["", "## Non-OK Rows", ""])
        for _, row in bad.head(75).iterrows():
            lines.append(f"- {row.get('event_id')} / {row.get('fact_name')}: {row.get('status')} expected={row.get('expected_value')} actual={row.get('actual_value')}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def _load_optional_context(path: str | Path | None) -> pd.DataFrame:
    if not path:
        return pd.DataFrame()
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)


def _lookup_external_context_row(row: pd.Series, context: pd.DataFrame) -> pd.Series:
    if context.empty:
        return pd.Series(dtype=object)
    event_id = _norm(row.get("event_id"))
    if "event_id" in context.columns:
        matched = context[context["event_id"].astype(str) == event_id]
        if not matched.empty:
            return matched.iloc[0]
    if "ticker" not in context.columns:
        return pd.Series(dtype=object)
    ticker = _norm(row.get("ticker")).upper()
    subset = context[context["ticker"].astype(str).str.upper() == ticker].copy()
    if subset.empty:
        return pd.Series(dtype=object)
    sort_col = "asof_date" if "asof_date" in subset.columns else ""
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
    include_same_day = _norm(release_session).lower() in {"after_close", "intraday", "market_hours", "unknown", ""}
    eligible = prices[prices["date"] <= date] if include_same_day else prices[prices["date"] < date]
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
    if pd.isna(start) or pd.isna(end) or start == 0:
        return np.nan
    return end / start - 1.0


def _window_volatility(prices: pd.DataFrame, anchor_date: pd.Timestamp | None, window: int) -> float:
    if anchor_date is None or prices.empty:
        return np.nan
    idx_matches = prices.index[prices["date"] == anchor_date].tolist()
    if not idx_matches:
        return np.nan
    idx = idx_matches[-1]
    start_idx = idx - int(window)
    if start_idx < 0:
        return np.nan
    returns = prices.iloc[start_idx : idx + 1]["adj_close"].astype(float).pct_change().dropna()
    return float(returns.std()) if not returns.empty else np.nan


def _size_bucket(market_cap: object) -> str:
    mc = _to_float(market_cap)
    if pd.isna(mc):
        return "unknown"
    if mc < 2_000_000_000:
        return "small_cap"
    if mc < 10_000_000_000:
        return "mid_cap"
    return "large_cap"


def _is_big4(name: object) -> bool:
    text = re.sub(r"[^A-Z0-9]+", " ", str(name or "").upper())
    return any(pattern in text for pattern in BIG4_PATTERNS)


def classify_accounting_integrity_execution_survivability(row: pd.Series | dict) -> dict[str, object]:
    event_type = _norm(row.get("accounting_integrity_event_type")).lower()
    severity = _norm(row.get("severity_pre_price")).lower()
    release_session = _norm(row.get("release_session"), "unknown").lower()
    non_reliance = _bool_value(row.get("non_reliance_flag"))
    disagreement = _bool_value(row.get("disagreement_flag"))
    reportable = _bool_value(row.get("reportable_event_flag"))
    hard_negative = _bool_value(row.get("hard_negative_flag")) or event_type == "routine_auditor_change"

    if hard_negative and severity != "high":
        cls = "explanation-only"
        rationale = "Routine auditor rotations, dismissals with no disagreement, and boilerplate internal-control language are not pre-registered as tradable negative signals."
    elif release_session in {"after_close", "before_open"} and (non_reliance or disagreement or reportable):
        cls = "immediate-gap"
        rationale = "The disclosure is likely incorporated into the first next-open print; any close-to-close effect can be explanatory without being realistically tradable."
    elif non_reliance or event_type in {"restatement_warning", "accounting_error_correction"}:
        cls = "delayed-digestion"
        rationale = "Non-reliance and restatement scope can require investors to read affected periods, controls, and auditor exhibits, leaving a possible post-open digestion window only if next-open behavior survives stress."
    elif event_type in {"internal_control_issue", "reportable_event"}:
        cls = "slow-burn repricing"
        rationale = "Controls and reportable-event disclosures may reprice through follow-on financing, filing-delay, or auditor-risk channels rather than an immediately clean gap."
    else:
        cls = "pre-event setup"
        rationale = "The event may matter mainly when it confirms prior accounting-risk setup; this cannot be treated as a standalone post-disclosure trade without setup controls."

    return {
        "execution_survivability_class": cls,
        "first_realistic_entry": "next_open_after_sec_acceptance",
        "tradeability_after_first_entry_rationale": rationale,
        "next_open_required_flag": True,
        "close_to_close_explanatory_only_flag": True,
    }


def enrich_accounting_integrity_context(
    events_path: str | Path,
    prices_dir: str | Path,
    out_path: str | Path,
    *,
    benchmark_ticker: str = "SPY",
    market_caps_path: str | Path | None = None,
) -> pd.DataFrame:
    events = pd.read_csv(events_path)
    market_caps = _load_optional_context(market_caps_path)
    price_cache: dict[str, pd.DataFrame] = {}
    try:
        benchmark_prices = load_price_csv(prices_dir, benchmark_ticker.upper())
    except FileNotFoundError:
        benchmark_prices = pd.DataFrame()

    enriched_rows = []
    sortable = events.copy()
    sortable["_event_time_sort"] = pd.to_datetime(sortable.get("event_time"), errors="coerce")
    for _, row in sortable.iterrows():
        out = row.drop(labels=[c for c in ["_event_time_sort"] if c in row.index]).to_dict()
        ticker = _norm(row.get("ticker")).upper()
        status = []
        try:
            prices = price_cache.setdefault(ticker, load_price_csv(prices_dir, ticker)) if ticker else pd.DataFrame()
        except FileNotFoundError:
            prices = pd.DataFrame()
            status.append("missing_ticker_prices")
        if benchmark_prices.empty:
            status.append("missing_benchmark_prices")

        anchor_date = None
        last_close = np.nan
        if not prices.empty:
            anchor_date, last_close = _anchor_price(prices, row.get("event_time"), row.get("release_session"))
            if pd.isna(last_close):
                status.append("missing_pre_event_close")
        out["price_anchor_date"] = anchor_date.date().isoformat() if anchor_date is not None else ""
        out["last_close_before_event"] = last_close

        market_cap = _to_float(row.get("market_cap_before_event", np.nan))
        if pd.isna(market_cap):
            ctx = _lookup_external_context_row(row, market_caps)
            if not ctx.empty:
                market_cap = _to_float(ctx.get("market_cap_before_event", np.nan))
        out["market_cap_before_event"] = market_cap
        if pd.isna(market_cap):
            status.append("missing_market_cap")
        out["company_size_bucket"] = _size_bucket(market_cap)

        bench_anchor, _ = _anchor_price(benchmark_prices, row.get("event_time"), row.get("release_session")) if not benchmark_prices.empty else (None, np.nan)
        stock_ret = _window_return(prices, anchor_date, 20) if not prices.empty else np.nan
        bench_ret = _window_return(benchmark_prices, bench_anchor, 20) if not benchmark_prices.empty else np.nan
        out["pre_event_market_adjusted_return_20d"] = stock_ret - bench_ret if pd.notna(stock_ret) and pd.notna(bench_ret) else np.nan
        out["pre_event_volatility_20d"] = _window_volatility(prices, anchor_date, 20) if not prices.empty else np.nan
        out["auditor_big4_flag"] = _is_big4(row.get("prior_auditor")) or _is_big4(row.get("new_auditor"))
        out.update(classify_accounting_integrity_execution_survivability(out))

        event_time = pd.to_datetime(row.get("event_time"), errors="coerce")
        if pd.notna(event_time) and ticker:
            prior = sortable[
                (sortable["ticker"].astype(str).str.upper() == ticker)
                & (sortable["_event_time_sort"] < event_time)
                & (sortable["_event_time_sort"] >= event_time - pd.Timedelta(days=365))
            ]
            out["prior_12m_accounting_events"] = int(len(prior))
        else:
            out["prior_12m_accounting_events"] = np.nan
        if "prior_late_filing_flag" not in out:
            out["prior_late_filing_flag"] = False

        context_cols = ["market_cap_before_event", "pre_event_market_adjusted_return_20d", "pre_event_volatility_20d"]
        for col in context_cols:
            if pd.isna(out.get(col)):
                status.append(f"missing_{col}")
        out["accounting_integrity_context_status"] = "ok" if not status else ";".join(sorted(set(status)))
        enriched_rows.append(out)
    enriched = pd.DataFrame(enriched_rows)
    ensure_parent(out_path)
    enriched.to_csv(out_path, index=False)
    return enriched


def audit_accounting_integrity_timestamps_and_duplicates(events: pd.DataFrame, out_path: str | Path | None = None) -> tuple[pd.DataFrame, dict[str, object]]:
    rows = []
    df = events.copy()
    if df.empty:
        audit = pd.DataFrame(columns=["event_id", "timestamp_status", "duplicate_status", "audit_status"])
        summary = {"rows": 0, "clear_timestamps": 0, "duplicates": 0, "audit_pass": False}
    else:
        key_parts = []
        for _, row in df.iterrows():
            accession = _norm(row.get("accession_number"))
            key = accession or "|".join(
                [
                    _norm(row.get("ticker")).upper(),
                    _norm(row.get("item_number")),
                    _norm(row.get("affected_periods")),
                    pd.to_datetime(row.get("event_time"), errors="coerce").date().isoformat()
                    if pd.notna(pd.to_datetime(row.get("event_time"), errors="coerce"))
                    else "",
                ]
            )
            key_parts.append(key)
        df["_duplicate_key"] = key_parts
        counts = df["_duplicate_key"].value_counts()
        seen: set[str] = set()
        for _, row in df.iterrows():
            session = _norm(row.get("release_session"), "unknown").lower()
            timestamp_status = "clear" if session in {"before_open", "intraday", "after_close"} and pd.notna(pd.to_datetime(row.get("event_time"), errors="coerce")) else "unclear"
            key = row["_duplicate_key"]
            duplicate_status = "primary"
            if counts.get(key, 0) > 1:
                duplicate_status = "primary" if key not in seen else "duplicate"
                seen.add(key)
            rows.append(
                {
                    "event_id": row.get("event_id"),
                    "ticker": row.get("ticker"),
                    "timestamp_status": timestamp_status,
                    "duplicate_status": duplicate_status,
                    "duplicate_key": key,
                    "audit_status": "ok" if timestamp_status == "clear" and duplicate_status == "primary" else "needs_review",
                }
            )
        audit = pd.DataFrame(rows)
        summary = {
            "rows": int(len(audit)),
            "clear_timestamps": int((audit["timestamp_status"] == "clear").sum()),
            "duplicates": int((audit["duplicate_status"] == "duplicate").sum()),
            "audit_pass": bool((audit["timestamp_status"] == "clear").all() and (audit["duplicate_status"] != "duplicate").all()),
        }
    if out_path:
        ensure_parent(out_path)
        audit.to_csv(out_path, index=False)
    return audit, summary


def accounting_integrity_readiness_summary(
    events: pd.DataFrame,
    *,
    source_documents: pd.DataFrame | None = None,
    parser_errors: pd.DataFrame | None = None,
    timestamp_audit: pd.DataFrame | None = None,
    min_train: int = 40,
) -> dict[str, object]:
    if events.empty:
        return {
            "decision": "source discovery insufficient",
            "reason": "no parsed Item 4.01/4.02 event rows",
            "parsed_event_rows": 0,
            "gates": {"source_documents_recovered_100": False},
            "top_missing_fields_blocking_modeling": ["source_documents_recovered_100"],
        }

    review_status = events.get("review_status", pd.Series([""] * len(events), index=events.index)).fillna("").astype(str).str.lower()
    usable = events[~review_status.isin({"rejected", "drop", "dropped"})].copy()
    reviewed = usable[usable.get("review_status", pd.Series([""] * len(usable), index=usable.index)).fillna("").astype(str).str.lower().isin({"reviewed", "curated", "approved"})]
    high_severity = reviewed[reviewed.get("severity_pre_price", pd.Series([""] * len(reviewed), index=reviewed.index)).astype(str).str.lower().eq("high")]
    non_reliance = reviewed[reviewed.get("non_reliance_flag", pd.Series(False, index=reviewed.index)).map(_bool_value)]
    resignation_or_disagreement = reviewed[
        reviewed.get("auditor_change_type", pd.Series([""] * len(reviewed), index=reviewed.index)).astype(str).str.lower().eq("resignation")
        | reviewed.get("disagreement_flag", pd.Series(False, index=reviewed.index)).map(_bool_value)
        | reviewed.get("reportable_event_flag", pd.Series(False, index=reviewed.index)).map(_bool_value)
    ]
    rows_with_context = int(
        (
            reviewed.get("market_cap_before_event", pd.Series(index=reviewed.index, dtype=float)).notna()
            & reviewed.get("pre_event_market_adjusted_return_20d", pd.Series(index=reviewed.index, dtype=float)).notna()
            & reviewed.get("pre_event_volatility_20d", pd.Series(index=reviewed.index, dtype=float)).notna()
        ).sum()
    )
    survivability_classes = {}
    if "execution_survivability_class" in events.columns:
        survivability_classes = {
            str(k): int(v)
            for k, v in events["execution_survivability_class"].fillna("unclassified").astype(str).value_counts().items()
        }
    next_open_rows = int(events.get("next_open_return", pd.Series(index=events.index, dtype=float)).notna().sum())
    stress_cols = [
        "next_open_return_stress_25bps",
        "next_open_return_stress_50bps",
        "next_open_return_stress_100bps",
        "close_to_close_return",
    ]
    rows_with_execution_stress = int(events[stress_cols].notna().all(axis=1).sum()) if all(c in events.columns for c in stress_cols) else 0
    source_rows = int(len(source_documents)) if source_documents is not None else np.nan
    clear_timestamp_rows = 0
    duplicate_rows = 0
    if timestamp_audit is not None and not timestamp_audit.empty:
        clear_timestamp_rows = int((timestamp_audit.get("timestamp_status", pd.Series(dtype=str)) == "clear").sum())
        duplicate_rows = int((timestamp_audit.get("duplicate_status", pd.Series(dtype=str)) == "duplicate").sum())
    else:
        clear_timestamp_rows = int(events.get("release_session", pd.Series(["unknown"] * len(events), index=events.index)).astype(str).str.lower().isin({"before_open", "intraday", "after_close"}).sum())

    metrics: dict[str, object] = {
        "source_documents_recovered": source_rows,
        "parsed_event_rows": int(len(events)),
        "reviewed_usable_rows": int(len(reviewed)),
        "high_severity_reviewed_rows": int(len(high_severity)),
        "item_4_02_non_reliance_rows": int(len(non_reliance)),
        "auditor_resignation_disagreement_reportable_rows": int(len(resignation_or_disagreement)),
        "rows_with_market_context": rows_with_context,
        "clear_timestamp_rows": clear_timestamp_rows,
        "duplicate_rows": duplicate_rows,
        "execution_survivability_class_counts": survivability_classes,
        "rows_with_next_open_behavior": next_open_rows,
        "rows_with_close_to_close_and_25_50_100bps_stress": rows_with_execution_stress,
        "likely_oos_predictions_min_train": int(max(0, len(reviewed) - int(min_train))),
    }
    gates = {
        "source_documents_recovered_100": bool(source_rows >= 100) if not pd.isna(source_rows) else False,
        "reviewed_usable_events_80_min": metrics["reviewed_usable_rows"] >= 80,
        "high_severity_events_50": metrics["high_severity_reviewed_rows"] >= 50,
        "item_4_02_non_reliance_events_30": metrics["item_4_02_non_reliance_rows"] >= 30,
        "auditor_resignation_disagreement_reportable_events_20": metrics["auditor_resignation_disagreement_reportable_rows"] >= 20,
        "market_context_rows_60": rows_with_context >= 60,
        "clear_timestamps_80": clear_timestamp_rows >= 80,
        "no_duplicate_primary_events": duplicate_rows == 0,
        "execution_survivability_classified": bool(survivability_classes) and sum(survivability_classes.values()) == len(events),
        "next_open_and_stress_ready_before_tradeability": rows_with_execution_stress >= 60,
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
        gates["parser_audit_pass"] = False
    blockers = [gate for gate, passed in gates.items() if not passed]
    metrics["gates"] = gates
    metrics["top_missing_fields_blocking_modeling"] = blockers
    if all(gates.values()):
        metrics["decision"] = "model-ready"
        metrics["reason"] = "all non-modeling readiness gates pass; eligible for first falsification only"
    elif not gates["source_documents_recovered_100"]:
        metrics["decision"] = "source discovery insufficient"
        metrics["reason"] = "SEC Item 4.01/4.02 source corpus is below the minimum discovery gate"
    elif not gates["parser_audit_pass"]:
        metrics["decision"] = "parser not trusted"
        metrics["reason"] = "human-reviewed parser audit is missing or failing"
    elif not gates["clear_timestamps_80"] or not gates["no_duplicate_primary_events"]:
        metrics["decision"] = "timestamp/duplicate audit insufficient"
        metrics["reason"] = "public timestamp or duplicate controls are not ready"
    elif not gates["market_context_rows_60"]:
        metrics["decision"] = "context insufficient"
        metrics["reason"] = "market cap, pre-event run-up, or volatility coverage is under-covered"
    elif not gates["execution_survivability_classified"] or not gates["next_open_and_stress_ready_before_tradeability"]:
        metrics["decision"] = "execution survivability insufficient"
        metrics["reason"] = "classification, next-open behavior, or 25/50/100 bps stress coverage is not ready"
    else:
        metrics["decision"] = "continue corpus buildout"
        metrics["reason"] = "reviewed usable event counts are below modeling gates"
    return metrics


def write_accounting_integrity_readiness_report(
    events_path: str | Path,
    out_path: str | Path,
    *,
    source_documents_path: str | Path | None = None,
    parser_errors_path: str | Path | None = None,
    timestamp_audit_path: str | Path | None = None,
    min_train: int = 40,
) -> dict[str, object]:
    events = pd.read_csv(events_path)
    source_documents = pd.read_csv(source_documents_path) if source_documents_path else None
    parser_errors = pd.read_csv(parser_errors_path) if parser_errors_path else None
    timestamp_audit = pd.read_csv(timestamp_audit_path) if timestamp_audit_path else None
    summary = accounting_integrity_readiness_summary(
        events,
        source_documents=source_documents,
        parser_errors=parser_errors,
        timestamp_audit=timestamp_audit,
        min_train=min_train,
    )
    out = ensure_parent(out_path)
    lines = [
        "# Accounting Integrity 8-K Readiness Report",
        "",
        "This is a data-readiness report, not a prediction result.",
        "",
        "## One-Page Verdict",
        "",
        f"- verdict: {summary.get('decision')}",
        f"- reason: {summary.get('reason')}",
        "",
        "## Summary Counts",
        "",
    ]
    for key, value in summary.items():
        if key in {"gates", "top_missing_fields_blocking_modeling", "decision", "reason"}:
            continue
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Gates", ""])
    for gate, passed in (summary.get("gates", {}) or {}).items():
        lines.append(f"- {gate}: {'PASS' if passed else 'FAIL'}")
    lines.extend(["", "## Top Missing Fields / Gates Blocking Modeling", ""])
    for blocker in summary.get("top_missing_fields_blocking_modeling", []) or []:
        lines.append(f"- {blocker}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
