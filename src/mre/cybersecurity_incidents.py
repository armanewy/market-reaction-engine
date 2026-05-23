from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Iterable

import numpy as np
import pandas as pd

from .ingestion import IngestionDiagnostics, build_sec_source_document_manifest
from .paths import ensure_parent
from .prices import load_price_csv
from .sec import SecClient
from .source_docs import SourceDocument, load_source_documents, make_source_docs_template


CYBERSECURITY_INCIDENT_DOMAIN = "cybersecurity_material_incidents_8k"

CYBERSECURITY_INCIDENT_EVENT_TYPES = {
    "material_cyber_incident",
    "ransomware",
    "business_interruption",
    "customer_data_breach",
    "third_party_vendor_breach",
    "operational_disruption",
    "incident_update",
    "no_material_impact_update",
    "legacy_cyber_disclosure",
    "generic_cyber_risk_control",
}

CYBERSECURITY_SEC_FORMS = ("8-K", "8-K/A")
CYBERSECURITY_ITEM_FILTER = "1.05"
CYBERSECURITY_EXHIBIT_PATTERN = r"(?i)(ex[-_]?99|exhibit[-_ ]?99|dex99|99[._-]?1|press[-_ ]?release|cyber|incident|ransom|security|breach)"

CYBERSECURITY_FACT_COLUMNS = [
    "source_doc_id",
    "event_id",
    "ticker",
    "event_time",
    "fact_name",
    "value",
    "unit",
    "source_evidence_text",
    "evidence_text",
    "confidence",
    "parse_method",
    "parser_quality_flags",
    "source_type",
    "source_url",
]

CYBERSECURITY_FEATURE_COLUMNS = [
    "event_id",
    "ticker",
    "event_time",
    "source_doc_ids",
    "usable_fact_count",
    "source_type",
    "source_url",
    "source_evidence_text",
    "cybersecurity_incident_event_type",
    "event_type",
    "item_105_flag",
    "legacy_disclosure_flag",
    "incident_discovery_date",
    "materiality_determination_date",
    "operational_disruption_flag",
    "ransomware_flag",
    "customer_data_exposure_flag",
    "third_party_vendor_flag",
    "financial_impact_language",
    "business_interruption_language",
    "amendment_update_flag",
    "no_material_impact_language",
    "known_publicly_before_filing_flag",
    "hard_negative_flag",
    "hard_negative_reason",
    "event_direction_pre_price",
    "materiality_pre_price",
    "label_quality",
    "evidence_status",
    "parser_quality_flags",
    "market_cap_before_event",
    "sector",
    "pre_event_market_adjusted_return_20d",
    "pre_event_volatility_20d",
    "company_size_bucket",
    "revenue_ltm_if_available",
    "data_sensitive_sector_flag",
    "prior_cyber_incident_flag",
    "sector_benchmark",
]

HARD_NEGATIVE_EVENT_TYPES = {"generic_cyber_risk_control", "no_material_impact_update"}


@dataclass(frozen=True)
class CybersecurityIncidentFact:
    source_doc_id: str
    event_id: str
    ticker: str
    event_time: str
    fact_name: str
    value: str | float | bool
    unit: str
    source_evidence_text: str
    confidence: float
    parse_method: str
    parser_quality_flags: str = ""
    source_type: str = ""
    source_url: str = ""

    def to_dict(self) -> dict:
        out = asdict(self)
        out["evidence_text"] = self.source_evidence_text
        return out


def _norm(value: object, default: str = "") -> str:
    text = str(value if value is not None else "").strip()
    if text.lower() in {"nan", "none", "null", "nat"}:
        return default
    return text or default


def _norm_space(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _segments(text: str) -> list[str]:
    parts: list[str] = []
    for raw in re.split(r"(?<!\d)[\.;!?](?!\d)|\n+", str(text or "")):
        seg = _norm_space(raw)
        if 10 <= len(seg) <= 900:
            parts.append(seg)
    return parts


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    low = text.lower()
    return any(str(term).lower() in low for term in terms)


def _first_matching_segment(text: str, patterns: Iterable[str]) -> str:
    for seg in _segments(text):
        for pattern in patterns:
            if re.search(pattern, seg, flags=re.I):
                return seg
    return ""


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _to_float(value: object) -> float:
    return float(pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0])


def _parse_date_from_segment(segment: str, cue_patterns: Iterable[str]) -> tuple[str, str]:
    date_pattern = (
        r"(?P<date>(?:20|19)\d{2}[-/]\d{1,2}[-/]\d{1,2}|"
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+(?:20|19)\d{2})"
    )
    for pattern in cue_patterns:
        match = re.search(pattern + r".{0,120}?" + date_pattern, segment, flags=re.I)
        if not match:
            match = re.search(date_pattern + r".{0,120}?" + pattern, segment, flags=re.I)
        if match:
            ts = pd.to_datetime(match.group("date"), errors="coerce")
            if pd.notna(ts):
                return pd.Timestamp(ts).date().isoformat(), segment
    return "", ""


def _fact(
    doc: SourceDocument,
    name: str,
    value: str | float | bool,
    unit: str,
    evidence: str,
    confidence: float,
    method: str,
    flags: Iterable[str] | str = "",
) -> CybersecurityIncidentFact:
    flag_text = flags if isinstance(flags, str) else ";".join(sorted({str(f) for f in flags if str(f).strip()}))
    return CybersecurityIncidentFact(
        source_doc_id=doc.source_doc_id,
        event_id=doc.event_id,
        ticker=doc.ticker,
        event_time=doc.event_time.isoformat(),
        fact_name=name,
        value=value,
        unit=unit,
        source_evidence_text=_norm_space(evidence),
        confidence=float(np.clip(confidence, 0.0, 0.99)),
        parse_method=method,
        parser_quality_flags=flag_text,
        source_type=doc.source_type,
        source_url=doc.source_url,
    )


def _item_105_signal(doc: SourceDocument, text: str) -> tuple[bool, str, float]:
    haystack = "\n".join([doc.event_subtype, doc.source_type, doc.title, doc.notes, text[:3000]])
    evidence = _first_matching_segment(haystack, [r"\bItem\s+1\.05\b", r"material cybersecurity incident"])
    if evidence:
        return True, evidence, 0.96
    return False, "", 0.15


def _hard_negative_flags(text: str) -> list[str]:
    low = text.lower()
    flags: list[str] = []
    if _contains_any(low, ["risk factors", "cybersecurity risk management", "material weaknesses in cyber controls"]) and not _contains_any(
        low,
        ["experienced a cybersecurity incident", "identified a cybersecurity incident", "became aware of a cybersecurity incident", "unauthorized access", "ransomware"],
    ):
        flags.append("generic_cyber_risk_disclosure")
    if re.search(r"\b(vulnerability|zero-day|cve-|security advisory)\b", low) and _contains_any(low, ["third-party", "vendor", "supplier"]) and not _contains_any(
        low,
        ["our systems", "company systems", "affected our", "impacted our", "unauthorized access to"],
    ):
        flags.append("vendor_vulnerability_not_tied_to_company")
    if re.search(r"\bnot\s+material\b|\bnot\s+reasonably\s+likely\s+to\s+materially\b|\bno\s+material\s+(?:impact|effect)\b", low):
        flags.append("non_material_or_no_material_impact_language")
    if _contains_any(low, ["previously disclosed", "as previously reported", "previously announced"]) and not re.search(r"\bItem\s+1\.05\b", text, flags=re.I):
        flags.append("incident_known_publicly_before_filing")
    return list(dict.fromkeys(flags))


def _infer_event_type(text: str, item_105_flag: bool, flags: list[str]) -> tuple[str, str, float]:
    low = text.lower()
    if "generic_cyber_risk_disclosure" in flags:
        return "generic_cyber_risk_control", _first_matching_segment(text, [r"risk factors", r"cybersecurity risk management"]), 0.92
    if "vendor_vulnerability_not_tied_to_company" in flags:
        return "generic_cyber_risk_control", _first_matching_segment(text, [r"vulnerability", r"security advisory", r"third-party"]), 0.86
    if "non_material_or_no_material_impact_language" in flags and _contains_any(low, ["amend", "update", "8-k/a", "form 8-k/a"]):
        return "no_material_impact_update", _first_matching_segment(text, [r"no material impact", r"not material", r"not reasonably likely"]), 0.93
    if re.search(r"\bransomware\b|\bransom\b|\bextortion\b|\bencrypt(?:ed|ion)\b", low):
        return "ransomware", _first_matching_segment(text, [r"ransomware", r"ransom", r"extortion", r"encrypt"]), 0.92
    if re.search(r"\b(disrupted|disruption|outage|shut down|shutdown|offline|suspend(?:ed)? operations|business interruption)\b", low):
        return "business_interruption" if "business interruption" in low else "operational_disruption", _first_matching_segment(text, [r"business interruption", r"disrupt", r"outage", r"offline", r"operations"]), 0.88
    if re.search(r"\b(personal information|personally identifiable|customer data|protected health|patient|payment card|social security)\b", low):
        return "customer_data_breach", _first_matching_segment(text, [r"customer data", r"personal information", r"patient", r"payment card", r"social security"]), 0.86
    if re.search(r"\b(third[- ]party|vendor|supplier|service provider)\b", low) and _contains_any(low, ["incident", "breach", "unauthorized access"]):
        return "third_party_vendor_breach", _first_matching_segment(text, [r"third[- ]party", r"vendor", r"supplier", r"service provider"]), 0.82
    if _contains_any(low, ["update", "amendment", "8-k/a", "investigation is ongoing"]):
        return "incident_update", _first_matching_segment(text, [r"update", r"amendment", r"investigation is ongoing"]), 0.75
    if item_105_flag or _contains_any(low, ["material cybersecurity incident", "cybersecurity incident"]):
        return "material_cyber_incident", _first_matching_segment(text, [r"material cybersecurity incident", r"cybersecurity incident"]), 0.82
    if _contains_any(low, ["unauthorized access", "data breach", "cyber attack", "cyberattack"]):
        return "legacy_cyber_disclosure", _first_matching_segment(text, [r"unauthorized access", r"data breach", r"cyber ?attack"]), 0.70
    return "generic_cyber_risk_control", "", 0.35


def parse_cybersecurity_incident_document(doc: SourceDocument) -> list[CybersecurityIncidentFact]:
    text = "\n".join([doc.title, doc.text])
    low = text.lower()
    flags = _hard_negative_flags(text)
    item_105_flag, item_evidence, item_conf = _item_105_signal(doc, text)
    event_type, event_evidence, event_conf = _infer_event_type(text, item_105_flag, flags)

    discovery_date, discovery_evidence = "", ""
    materiality_date, materiality_evidence = "", ""
    for seg in _segments(text):
        if not discovery_date:
            discovery_date, discovery_evidence = _parse_date_from_segment(
                seg,
                [r"\bdiscovered\b", r"\bidentified\b", r"\bbecame aware\b", r"\bdetected\b"],
            )
        if not materiality_date:
            materiality_date, materiality_evidence = _parse_date_from_segment(
                seg,
                [r"\bdetermined\b.{0,40}\bmaterial", r"\bmateriality\b", r"\bmaterial cybersecurity incident\b"],
            )

    operational_evidence = _first_matching_segment(text, [r"disrupt", r"outage", r"offline", r"shut ?down", r"suspend(?:ed)? operations"])
    ransomware_evidence = _first_matching_segment(text, [r"ransomware", r"ransom", r"extortion", r"encrypt(?:ed|ion)"])
    customer_data_evidence = _first_matching_segment(text, [r"customer data", r"personal information", r"personally identifiable", r"protected health", r"payment card", r"social security"])
    vendor_evidence = _first_matching_segment(text, [r"third[- ]party", r"vendor", r"supplier", r"service provider"])
    financial_evidence = _first_matching_segment(text, [r"financial impact", r"material impact", r"costs?", r"expenses?", r"loss", r"revenue", r"insurance"])
    interruption_evidence = _first_matching_segment(text, [r"business interruption", r"disrupt", r"outage", r"offline", r"operations"])
    no_material_evidence = _first_matching_segment(text, [r"no material impact", r"not material", r"not reasonably likely"])
    amendment_evidence = _first_matching_segment(text, [r"amendment", r"8-k/a", r"update", r"investigation is ongoing"])
    known_before_evidence = _first_matching_segment(text, [r"previously disclosed", r"as previously reported", r"previously announced", r"publicly reported"])

    hard_negative = event_type in HARD_NEGATIVE_EVENT_TYPES or bool(flags)
    materiality = "low_control" if hard_negative else ("high" if item_105_flag else "medium")
    direction = "neutral_control" if hard_negative else "negative"

    facts = [
        _fact(doc, "item_105_flag", item_105_flag, "boolean", item_evidence, item_conf, "item_105_regex", flags),
        _fact(doc, "cybersecurity_incident_event_type", event_type, "category", event_evidence, event_conf, "event_type_rules", flags),
        _fact(doc, "incident_discovery_date", discovery_date, "date", discovery_evidence, 0.78 if discovery_date else 0.0, "date_regex", flags),
        _fact(doc, "materiality_determination_date", materiality_date, "date", materiality_evidence, 0.78 if materiality_date else 0.0, "date_regex", flags),
        _fact(doc, "operational_disruption_flag", bool(operational_evidence), "boolean", operational_evidence, 0.86 if operational_evidence else 0.25, "keyword_rules", flags),
        _fact(doc, "ransomware_flag", bool(ransomware_evidence), "boolean", ransomware_evidence, 0.92 if ransomware_evidence else 0.25, "keyword_rules", flags),
        _fact(doc, "customer_data_exposure_flag", bool(customer_data_evidence), "boolean", customer_data_evidence, 0.86 if customer_data_evidence else 0.25, "keyword_rules", flags),
        _fact(doc, "third_party_vendor_flag", bool(vendor_evidence), "boolean", vendor_evidence, 0.82 if vendor_evidence else 0.25, "keyword_rules", flags),
        _fact(doc, "financial_impact_language", financial_evidence, "text", financial_evidence, 0.78 if financial_evidence else 0.0, "keyword_rules", flags),
        _fact(doc, "business_interruption_language", interruption_evidence, "text", interruption_evidence, 0.80 if interruption_evidence else 0.0, "keyword_rules", flags),
        _fact(doc, "amendment_update_flag", bool(amendment_evidence), "boolean", amendment_evidence, 0.80 if amendment_evidence else 0.25, "keyword_rules", flags),
        _fact(doc, "no_material_impact_language", no_material_evidence, "text", no_material_evidence, 0.86 if no_material_evidence else 0.0, "keyword_rules", flags),
        _fact(doc, "known_publicly_before_filing_flag", bool(known_before_evidence), "boolean", known_before_evidence, 0.82 if known_before_evidence else 0.25, "keyword_rules", flags),
        _fact(doc, "hard_negative_flag", hard_negative, "boolean", ";".join(flags) or event_evidence, 0.90 if hard_negative else 0.60, "hard_negative_rules", flags),
        _fact(doc, "hard_negative_reason", ";".join(flags), "category", ";".join(flags), 0.90 if flags else 0.0, "hard_negative_rules", flags),
        _fact(doc, "event_direction_pre_price", direction, "category", event_evidence, 0.80, "direction_rules", flags),
        _fact(doc, "materiality_pre_price", materiality, "category", item_evidence or event_evidence, 0.80, "materiality_rules", flags),
    ]
    # Keep a tiny reference to the raw cyber terms so audit templates can inspect
    # why a document was retained even when the typed facts are sparse.
    if not any(f.value for f in facts if f.fact_name in {"item_105_flag", "operational_disruption_flag", "ransomware_flag", "customer_data_exposure_flag"}):
        facts.append(_fact(doc, "parser_candidate_evidence", _first_matching_segment(text, [r"cyber", r"security", r"incident", r"breach"]), "text", text[:500], 0.35, "candidate_fallback", flags))
    return facts


def _best_fact(group: pd.DataFrame, name: str) -> pd.Series | None:
    subset = group[group["fact_name"].astype(str).eq(name)].copy()
    if subset.empty:
        return None
    subset["confidence_sort"] = pd.to_numeric(subset.get("confidence", 0.0), errors="coerce").fillna(0.0)
    return subset.sort_values("confidence_sort", ascending=False).iloc[0]


def _fact_value(group: pd.DataFrame, name: str, default: object = "") -> object:
    row = _best_fact(group, name)
    return default if row is None else row.get("value", default)


def cybersecurity_features_from_facts(facts: pd.DataFrame) -> pd.DataFrame:
    if facts.empty:
        return pd.DataFrame(columns=CYBERSECURITY_FEATURE_COLUMNS)
    rows: list[dict] = []
    for event_id, group in facts.groupby("event_id", dropna=False):
        first = group.iloc[0]
        event_type = _norm(_fact_value(group, "cybersecurity_incident_event_type", "generic_cyber_risk_control"))
        flags = ";".join(sorted({flag for text in group.get("parser_quality_flags", pd.Series(dtype=str)).fillna("").astype(str) for flag in text.split(";") if flag}))
        source_evidence = _norm(_fact_value(group, "cybersecurity_incident_event_type", ""))
        if not source_evidence:
            evidence_row = _best_fact(group, "item_105_flag")
            source_evidence = _norm(evidence_row.get("source_evidence_text")) if evidence_row is not None else ""
        hard_negative = _bool_value(_fact_value(group, "hard_negative_flag", False))
        row = {
            "event_id": event_id,
            "ticker": _norm(first.get("ticker")).upper(),
            "event_time": _norm(first.get("event_time")),
            "source_doc_ids": ";".join(sorted(group["source_doc_id"].dropna().astype(str).unique())),
            "usable_fact_count": int(group["value"].fillna("").astype(str).str.strip().ne("").sum()),
            "source_type": _norm(first.get("source_type")),
            "source_url": _norm(first.get("source_url")),
            "source_evidence_text": source_evidence,
            "cybersecurity_incident_event_type": event_type,
            "event_type": event_type,
            "item_105_flag": _bool_value(_fact_value(group, "item_105_flag", False)),
            "legacy_disclosure_flag": event_type == "legacy_cyber_disclosure",
            "incident_discovery_date": _norm(_fact_value(group, "incident_discovery_date", "")),
            "materiality_determination_date": _norm(_fact_value(group, "materiality_determination_date", "")),
            "operational_disruption_flag": _bool_value(_fact_value(group, "operational_disruption_flag", False)),
            "ransomware_flag": _bool_value(_fact_value(group, "ransomware_flag", False)),
            "customer_data_exposure_flag": _bool_value(_fact_value(group, "customer_data_exposure_flag", False)),
            "third_party_vendor_flag": _bool_value(_fact_value(group, "third_party_vendor_flag", False)),
            "financial_impact_language": _norm(_fact_value(group, "financial_impact_language", "")),
            "business_interruption_language": _norm(_fact_value(group, "business_interruption_language", "")),
            "amendment_update_flag": _bool_value(_fact_value(group, "amendment_update_flag", False)),
            "no_material_impact_language": _norm(_fact_value(group, "no_material_impact_language", "")),
            "known_publicly_before_filing_flag": _bool_value(_fact_value(group, "known_publicly_before_filing_flag", False)),
            "hard_negative_flag": hard_negative,
            "hard_negative_reason": _norm(_fact_value(group, "hard_negative_reason", "")),
            "event_direction_pre_price": _norm(_fact_value(group, "event_direction_pre_price", "negative" if not hard_negative else "neutral_control")),
            "materiality_pre_price": _norm(_fact_value(group, "materiality_pre_price", "high" if not hard_negative else "low_control")),
            "label_quality": "unreviewed",
            "evidence_status": "source_backed" if source_evidence else "missing",
            "parser_quality_flags": flags,
            "market_cap_before_event": np.nan,
            "sector": "",
            "pre_event_market_adjusted_return_20d": np.nan,
            "pre_event_volatility_20d": np.nan,
            "company_size_bucket": "unknown",
            "revenue_ltm_if_available": np.nan,
            "data_sensitive_sector_flag": False,
            "prior_cyber_incident_flag": False,
            "sector_benchmark": "",
        }
        rows.append(row)
    return pd.DataFrame(rows, columns=CYBERSECURITY_FEATURE_COLUMNS)


def cybersecurity_features_to_events(features: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for _, row in features.iterrows():
        hard_negative = _bool_value(row.get("hard_negative_flag"))
        summary = _norm(row.get("source_evidence_text"))[:240]
        rows.append(
            {
                "event_id": _norm(row.get("event_id")),
                "ticker": _norm(row.get("ticker")).upper(),
                "event_time": _norm(row.get("event_time")),
                "event_type": "cybersecurity",
                "event_subtype": _norm(row.get("cybersecurity_incident_event_type")),
                "event_family": CYBERSECURITY_INCIDENT_DOMAIN,
                "summary": summary,
                "source_type": _norm(row.get("source_type")),
                "source_url": _norm(row.get("source_url")),
                "release_session": "unknown",
                "expectedness": "unknown",
                "surprise_direction": "negative" if not hard_negative else "none",
                "surprise_magnitude": "unknown",
                "materiality": 0.7 if not hard_negative else 0.1,
                "sector_benchmark": _norm(row.get("sector_benchmark")),
                "notes": _norm(row.get("parser_quality_flags")),
                "corpus_name": CYBERSECURITY_INCIDENT_DOMAIN,
                "review_status": "unreviewed",
                "label_quality": _norm(row.get("label_quality"), "unreviewed"),
                "source_doc_ids": _norm(row.get("source_doc_ids")),
                "evidence_status": _norm(row.get("evidence_status")),
                **{col: row.get(col, "") for col in CYBERSECURITY_FEATURE_COLUMNS if col not in {"event_id", "ticker", "event_time", "event_type", "sector_benchmark"}},
            }
        )
    return pd.DataFrame(rows)


def parse_cybersecurity_incident_manifest(
    manifest_path: str | Path,
    facts_out: str | Path,
    features_out: str | Path,
    events_out: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    docs = load_source_documents(manifest_path)
    fact_rows = [fact.to_dict() for doc in docs for fact in parse_cybersecurity_incident_document(doc)]
    facts = pd.DataFrame(fact_rows, columns=CYBERSECURITY_FACT_COLUMNS)
    features = cybersecurity_features_from_facts(facts)
    events = cybersecurity_features_to_events(features)
    ensure_parent(facts_out)
    facts.to_csv(facts_out, index=False)
    ensure_parent(features_out)
    features.to_csv(features_out, index=False)
    ensure_parent(events_out)
    events.to_csv(events_out, index=False)
    return facts, features, events


def build_cybersecurity_incident_source_documents(
    *,
    client: SecClient,
    tickers: Iterable[str],
    out_manifest: str | Path,
    docs_dir: str | Path,
    source_manifests: Iterable[str | Path] | None = None,
    start: str = "2023-12-18",
    end: str | None = None,
    limit_per_ticker: int | None = 80,
    sector_benchmark: str = "",
    overwrite: bool = False,
) -> tuple[pd.DataFrame, IngestionDiagnostics]:
    sec_docs, diag = build_sec_source_document_manifest(
        client,
        tickers=tickers,
        out_manifest=out_manifest,
        docs_dir=docs_dir,
        forms=CYBERSECURITY_SEC_FORMS,
        start=start,
        end=end,
        item_filter=CYBERSECURITY_ITEM_FILTER,
        limit_per_ticker=limit_per_ticker,
        include_primary=True,
        include_exhibits=True,
        exhibit_pattern=CYBERSECURITY_EXHIBIT_PATTERN,
        sector_benchmark=sector_benchmark,
        overwrite=overwrite,
    )
    frames = [sec_docs]
    for manifest in source_manifests or []:
        frames.append(pd.read_csv(manifest))
    out = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    if not out.empty:
        out["event_family"] = CYBERSECURITY_INCIDENT_DOMAIN
        out["event_type"] = "cybersecurity"
        out["event_subtype"] = out.get("event_subtype", pd.Series("", index=out.index)).fillna("").replace("", "sec_8_k_item_1_05")
    make_source_docs_template(out_manifest, rows=out.to_dict("records"))
    diag.rows_written = int(len(out))
    return out, diag


def validate_cybersecurity_incident_parser(facts: pd.DataFrame, gold: pd.DataFrame, out_errors: str | Path | None = None) -> tuple[pd.DataFrame, dict[str, object]]:
    if gold.empty:
        report = {"status": "missing_gold_set", "parser_audit_pass": False, "gold_rows": 0}
        errors = pd.DataFrame(columns=["event_id", "fact_name", "status", "expected_value", "actual_value"])
        return errors, report

    review_col = "gold_review_status" if "gold_review_status" in gold.columns else "review_status"
    if review_col in gold.columns:
        reviewed = gold[gold[review_col].fillna("").astype(str).str.lower().isin({"reviewed", "approved", "curated"})].copy()
        if reviewed.empty:
            errors = gold.copy()
            errors["status"] = "gold_not_reviewed"
            report = {
                "status": "gold_set_requires_human_review",
                "gold_rows": int(len(gold)),
                "reviewed_gold_rows": 0,
                "parser_audit_pass": False,
                "gates": {"gold_set_human_reviewed": False},
            }
            if out_errors:
                ensure_parent(out_errors)
                errors.to_csv(out_errors, index=False)
            return errors, report
        gold = reviewed

    rows: list[dict] = []
    facts_idx = facts.copy()
    facts_idx["event_id"] = facts_idx.get("event_id", pd.Series(dtype=str)).astype(str)
    facts_idx["fact_name"] = facts_idx.get("fact_name", pd.Series(dtype=str)).astype(str)
    for _, expected in gold.iterrows():
        event_id = str(expected.get("event_id", ""))
        fact_name = str(expected.get("fact_name", ""))
        expected_value = expected.get("expected_value", "")
        expected_present = expected.get("expected_present", True)
        expected_present_bool = True if pd.isna(expected_present) else _bool_value(expected_present)
        matches = facts_idx[(facts_idx["event_id"].eq(event_id)) & (facts_idx["fact_name"].eq(fact_name))]
        actual_value = "" if matches.empty else matches.iloc[0].get("value", "")
        if matches.empty:
            status = "ok" if not expected_present_bool else "missing"
        elif not expected_present_bool:
            status = "ok" if str(actual_value).strip().lower() in {"", "false", "0", "unknown", "generic_cyber_risk_control", "no_material_impact_update"} else "false_positive"
        else:
            exp_num = pd.to_numeric(pd.Series([expected_value]), errors="coerce").iloc[0]
            act_num = pd.to_numeric(pd.Series([actual_value]), errors="coerce").iloc[0]
            if pd.notna(exp_num) and pd.notna(act_num):
                tolerance = pd.to_numeric(pd.Series([expected.get("tolerance", 0)]), errors="coerce").fillna(0).iloc[0]
                status = "ok" if abs(float(exp_num) - float(act_num)) <= float(tolerance) else "mismatch"
            else:
                status = "ok" if str(expected_value).strip().lower() == str(actual_value).strip().lower() else "mismatch"
        rows.append(
            {
                "event_id": event_id,
                "fact_name": fact_name,
                "status": status,
                "expected_value": expected_value,
                "actual_value": actual_value,
                "expected_present": expected_present_bool,
                "gold_category": expected.get("gold_category", ""),
            }
        )
    errors = pd.DataFrame(rows)
    ok_count = int(errors["status"].eq("ok").sum()) if not errors.empty else 0
    accuracy = ok_count / len(errors) if len(errors) else 0.0
    event_type = errors[errors["fact_name"].eq("cybersecurity_incident_event_type")]
    event_type_precision = float(event_type["status"].eq("ok").mean()) if len(event_type) else 0.0
    hard_negative_false_material = False
    if "gold_category" in errors.columns:
        hard_negative_false_material = bool(
            (
                errors["gold_category"].astype(str).str.contains("hard_negative|generic|non_material|vendor_vulnerability", case=False, regex=True)
                & errors["actual_value"].astype(str).str.lower().isin({"material_cyber_incident", "ransomware", "business_interruption", "operational_disruption", "customer_data_breach"})
                & errors["status"].ne("ok")
            ).any()
        )
    gates = {
        "gold_set_60_rows": len(errors) >= 60,
        "row_accuracy_90": accuracy >= 0.90,
        "event_type_precision_95": event_type_precision >= 0.95 if len(event_type) else accuracy >= 0.90,
        "no_hard_negative_mistaken_for_material_incident": not hard_negative_false_material,
    }
    report = {
        "gold_rows": int(len(errors)),
        "correct_rows": ok_count,
        "row_accuracy": float(accuracy),
        "event_type_precision": event_type_precision,
        "parser_audit_pass": bool(all(gates.values())),
        "gates": gates,
    }
    if out_errors:
        ensure_parent(out_errors)
        errors.to_csv(out_errors, index=False)
    return errors, report


def _load_optional_context(path: str | Path | None) -> pd.DataFrame:
    if not path:
        return pd.DataFrame()
    p = Path(path)
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def _lookup_context_row(row: pd.Series, context: pd.DataFrame) -> pd.Series:
    if context.empty or "ticker" not in context.columns:
        return pd.Series(dtype=object)
    ticker = _norm(row.get("ticker")).upper()
    subset = context[context["ticker"].astype(str).str.upper().eq(ticker)].copy()
    if subset.empty:
        return pd.Series(dtype=object)
    if "asof_date" in subset.columns:
        subset["asof_date"] = pd.to_datetime(subset["asof_date"], errors="coerce").dt.tz_localize(None)
        event_time = pd.to_datetime(row.get("event_time"), errors="coerce")
        if pd.notna(event_time):
            event_time = event_time.tz_localize(None) if getattr(event_time, "tzinfo", None) else event_time
            subset = subset[subset["asof_date"] <= event_time]
        subset = subset.sort_values("asof_date", ascending=False)
    return subset.iloc[0] if not subset.empty else pd.Series(dtype=object)


def _anchor_price(prices: pd.DataFrame, event_time: object, release_session: object) -> tuple[pd.Timestamp | None, float]:
    ts = pd.to_datetime(event_time, errors="coerce")
    if pd.isna(ts):
        return None, np.nan
    ts = ts.tz_localize(None) if getattr(ts, "tzinfo", None) else ts
    date = ts.normalize()
    session = _norm(release_session).lower()
    include_same_day = session in {"after_close", "intraday", "market_hours", "unknown", ""}
    eligible = prices[prices["date"] <= date] if include_same_day else prices[prices["date"] < date]
    if eligible.empty:
        return None, np.nan
    last = eligible.iloc[-1]
    return pd.to_datetime(last["date"]), _to_float(last["adj_close"])


def _window_return(prices: pd.DataFrame, anchor_date: pd.Timestamp | None, window: int) -> float:
    if anchor_date is None or prices.empty:
        return np.nan
    idx_matches = prices.index[prices["date"].eq(anchor_date)].tolist()
    if not idx_matches or idx_matches[-1] - window < 0:
        return np.nan
    idx = idx_matches[-1]
    start = _to_float(prices.iloc[idx - window]["adj_close"])
    end = _to_float(prices.iloc[idx]["adj_close"])
    return end / start - 1.0 if pd.notna(start) and pd.notna(end) and start else np.nan


def _window_volatility(prices: pd.DataFrame, anchor_date: pd.Timestamp | None, window: int) -> float:
    if anchor_date is None or prices.empty:
        return np.nan
    idx_matches = prices.index[prices["date"].eq(anchor_date)].tolist()
    if not idx_matches or idx_matches[-1] - window < 1:
        return np.nan
    idx = idx_matches[-1]
    rets = prices.iloc[idx - window : idx + 1]["adj_close"].pct_change().dropna()
    return float(rets.std()) if len(rets) else np.nan


def _size_bucket(market_cap: object) -> str:
    mc = _to_float(market_cap)
    if pd.isna(mc):
        return "unknown"
    if mc < 2_000_000_000:
        return "small_cap"
    if mc < 10_000_000_000:
        return "mid_cap"
    return "large_cap"


def enrich_cybersecurity_incident_context(
    events_path: str | Path,
    prices_dir: str | Path,
    out_path: str | Path,
    *,
    benchmark_ticker: str = "SPY",
    market_caps_path: str | Path | None = None,
    revenue_path: str | Path | None = None,
    company_context_path: str | Path | None = None,
) -> pd.DataFrame:
    events = pd.read_csv(events_path)
    market_caps = _load_optional_context(market_caps_path)
    revenue = _load_optional_context(revenue_path)
    company_context = _load_optional_context(company_context_path)
    try:
        benchmark_prices = load_price_csv(prices_dir, benchmark_ticker.upper())
    except FileNotFoundError:
        benchmark_prices = pd.DataFrame()
    price_cache: dict[str, pd.DataFrame] = {}
    rows: list[dict] = []
    for _, row in events.iterrows():
        out = row.to_dict()
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
        bench_anchor, _ = _anchor_price(benchmark_prices, row.get("event_time"), row.get("release_session")) if not benchmark_prices.empty else (None, np.nan)
        stock_ret_20 = _window_return(prices, anchor_date, 20)
        bench_ret_20 = _window_return(benchmark_prices, bench_anchor, 20)
        out["pre_event_market_adjusted_return_20d"] = stock_ret_20 - bench_ret_20 if pd.notna(stock_ret_20) and pd.notna(bench_ret_20) else np.nan
        out["pre_event_volatility_20d"] = _window_volatility(prices, anchor_date, 20)
        out["last_close_before_event"] = last_close
        out["price_anchor_date"] = anchor_date.date().isoformat() if anchor_date is not None else ""

        market_row = _lookup_context_row(row, market_caps)
        market_cap = _to_float(row.get("market_cap_before_event", np.nan))
        if pd.isna(market_cap) and not market_row.empty:
            market_cap = _to_float(market_row.get("market_cap_before_event"))
        out["market_cap_before_event"] = market_cap
        out["company_size_bucket"] = _size_bucket(market_cap)
        if pd.isna(market_cap):
            status.append("missing_market_cap")

        revenue_row = _lookup_context_row(row, revenue)
        revenue_ltm = _to_float(row.get("revenue_ltm_if_available", np.nan))
        if pd.isna(revenue_ltm) and not revenue_row.empty:
            revenue_ltm = _to_float(revenue_row.get("revenue_ltm_if_available"))
        out["revenue_ltm_if_available"] = revenue_ltm

        company_row = _lookup_context_row(row, company_context)
        out["sector"] = _norm(row.get("sector")) or _norm(company_row.get("sector") if not company_row.empty else "")
        out["data_sensitive_sector_flag"] = _bool_value(row.get("data_sensitive_sector_flag", False)) or _bool_value(
            company_row.get("data_sensitive_sector_flag", False) if not company_row.empty else False
        )
        out["prior_cyber_incident_flag"] = _bool_value(row.get("prior_cyber_incident_flag", False)) or _bool_value(
            company_row.get("prior_cyber_incident_flag", False) if not company_row.empty else False
        )
        if pd.isna(out["pre_event_market_adjusted_return_20d"]):
            status.append("missing_pre_event_market_adjusted_return_20d")
        if pd.isna(out["pre_event_volatility_20d"]):
            status.append("missing_pre_event_volatility_20d")
        out["cybersecurity_context_status"] = "ok" if not status else ";".join(sorted(set(status)))
        rows.append(out)
    enriched = pd.DataFrame(rows)
    ensure_parent(out_path)
    enriched.to_csv(out_path, index=False)
    return enriched


def cybersecurity_timestamp_duplicate_audit(events: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    out = events.copy()
    if out.empty:
        return out, {"audited_rows": 0, "gates": {"no_duplicate_incident_counted_twice": False, "known_public_before_filing_excluded": False}}
    key_cols = [
        out.get("ticker", pd.Series("", index=out.index)).fillna("").astype(str).str.upper(),
        out.get("incident_discovery_date", pd.Series("", index=out.index)).fillna("").astype(str),
        out.get("materiality_determination_date", pd.Series("", index=out.index)).fillna("").astype(str),
        out.get("source_url", pd.Series("", index=out.index)).fillna("").astype(str).str.lower(),
    ]
    out["_duplicate_key"] = key_cols[0] + "|" + key_cols[1] + "|" + key_cols[2] + "|" + key_cols[3]
    out["duplicate_status"] = "primary"
    duplicate_mask = out["_duplicate_key"].duplicated(keep="first") & out["_duplicate_key"].str.strip("|").ne("")
    out.loc[duplicate_mask, "duplicate_status"] = "duplicate"
    known_before = out.get("known_publicly_before_filing_flag", pd.Series(False, index=out.index)).map(_bool_value)
    hard_negative = out.get("hard_negative_flag", pd.Series(False, index=out.index)).map(_bool_value)
    out["timestamp_duplicate_model_eligible_flag"] = (~duplicate_mask) & (~known_before) & (~hard_negative)
    summary = {
        "audited_rows": int(len(out)),
        "duplicate_rows": int(duplicate_mask.sum()),
        "known_publicly_before_filing_rows": int(known_before.sum()),
        "model_eligible_rows_after_timestamp_duplicate_audit": int(out["timestamp_duplicate_model_eligible_flag"].sum()),
        "gates": {
            "no_duplicate_incident_counted_twice": bool(not duplicate_mask.any()),
            "known_public_before_filing_excluded": bool(not (known_before & out["timestamp_duplicate_model_eligible_flag"]).any()),
        },
    }
    return out.drop(columns=["_duplicate_key"]), summary


def _reviewed_usable_events(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    review_status = events.get("review_status", pd.Series("", index=events.index)).fillna("").astype(str).str.lower()
    usable = events[review_status.isin({"reviewed", "curated", "approved"})].copy()
    hard_negative = usable.get("hard_negative_flag", pd.Series(False, index=usable.index)).map(_bool_value)
    known_before = usable.get("known_publicly_before_filing_flag", pd.Series(False, index=usable.index)).map(_bool_value)
    duplicate_ok = usable.get("duplicate_status", pd.Series("primary", index=usable.index)).fillna("primary").astype(str).str.lower().ne("duplicate")
    event_type = usable.get("cybersecurity_incident_event_type", usable.get("event_subtype", pd.Series("", index=usable.index))).fillna("").astype(str).str.lower()
    return usable[(~hard_negative) & (~known_before) & duplicate_ok & event_type.ne("") & ~event_type.isin(HARD_NEGATIVE_EVENT_TYPES)].copy()


def cybersecurity_incident_readiness_summary(
    events: pd.DataFrame,
    *,
    min_train: int = 40,
    source_documents: pd.DataFrame | None = None,
    parser_errors: pd.DataFrame | None = None,
) -> dict[str, object]:
    source_doc_rows = int(len(source_documents)) if source_documents is not None else int(events.get("source_doc_ids", pd.Series(dtype=str)).fillna("").astype(str).str.len().gt(0).sum())
    if events.empty:
        gates = {
            "reviewed_usable_events_80_min": False,
            "reviewed_usable_events_100_preferred": False,
            "item_105_events_50": False,
            "material_incident_events_50": False,
            "operational_or_ransomware_events_20": False,
            "market_cap_context_rows_40": False,
            "pre_event_context_rows_40": False,
            "clear_event_timestamps": False,
            "duplicate_timestamp_audit_pass": False,
            "hard_negative_review_pass": False,
            "likely_oos_predictions_30": False,
            "parser_audit_pass": False,
        }
        return {
            "source_documents_recovered": source_doc_rows,
            "parsed_event_rows": 0,
            "reviewed_usable_rows": 0,
            "gates": gates,
            "top_missing_fields_blocking_modeling": list(gates),
            "execution_survivability_classification": "delayed-digestion",
            "decision": "continue corpus buildout",
            "reason": "no parsed event rows",
        }

    reviewed = _reviewed_usable_events(events)
    event_type = reviewed.get("cybersecurity_incident_event_type", reviewed.get("event_subtype", pd.Series("", index=reviewed.index))).fillna("").astype(str).str.lower()
    item_105 = reviewed.get("item_105_flag", pd.Series(False, index=reviewed.index)).map(_bool_value)
    operational = reviewed.get("operational_disruption_flag", pd.Series(False, index=reviewed.index)).map(_bool_value)
    ransomware = reviewed.get("ransomware_flag", pd.Series(False, index=reviewed.index)).map(_bool_value)
    market_cap = pd.to_numeric(reviewed.get("market_cap_before_event", pd.Series(index=reviewed.index, dtype=float)), errors="coerce")
    pre_event_ret = pd.to_numeric(reviewed.get("pre_event_market_adjusted_return_20d", pd.Series(index=reviewed.index, dtype=float)), errors="coerce")
    pre_event_vol = pd.to_numeric(reviewed.get("pre_event_volatility_20d", pd.Series(index=reviewed.index, dtype=float)), errors="coerce")
    timestamps = pd.to_datetime(reviewed.get("event_time", pd.Series(index=reviewed.index, dtype=str)), errors="coerce")
    release_session = reviewed.get("release_session", pd.Series("unknown", index=reviewed.index)).fillna("unknown").astype(str).str.lower()
    hard_negative_reviewed = events.get("hard_negative_flag", pd.Series(False, index=events.index)).map(_bool_value)
    hard_negative_status = events.get("review_status", pd.Series("", index=events.index)).fillna("").astype(str).str.lower()
    duplicate_status = events.get("duplicate_status", pd.Series("primary", index=events.index)).fillna("primary").astype(str).str.lower()
    sector_benchmark = reviewed.get("sector_benchmark", pd.Series("", index=reviewed.index)).fillna("").astype(str).str.strip()

    metrics: dict[str, object] = {
        "source_documents_recovered": source_doc_rows,
        "parsed_event_rows": int(len(events)),
        "reviewed_usable_rows": int(len(reviewed)),
        "item_105_rows": int(item_105.sum()),
        "material_incident_rows": int(event_type.isin({"material_cyber_incident", "ransomware", "business_interruption", "customer_data_breach", "third_party_vendor_breach", "operational_disruption"}).sum()),
        "operational_or_ransomware_rows": int((operational | ransomware | event_type.isin({"business_interruption", "operational_disruption", "ransomware"})).sum()),
        "customer_data_exposure_rows": int(reviewed.get("customer_data_exposure_flag", pd.Series(False, index=reviewed.index)).map(_bool_value).sum()),
        "no_material_impact_update_rows": int(events.get("cybersecurity_incident_event_type", events.get("event_subtype", pd.Series("", index=events.index))).fillna("").astype(str).str.lower().eq("no_material_impact_update").sum()),
        "hard_negative_rows": int(hard_negative_reviewed.sum()),
        "reviewed_hard_negative_rows": int((hard_negative_reviewed & hard_negative_status.isin({"reviewed", "curated", "approved", "rejected"})).sum()),
        "duplicate_rows": int(duplicate_status.eq("duplicate").sum()),
        "rows_with_market_cap_context": int(market_cap.notna().sum()),
        "rows_with_pre_event_context": int((pre_event_ret.notna() & pre_event_vol.notna()).sum()),
        "rows_with_source_evidence": int(reviewed.get("source_evidence_text", pd.Series("", index=reviewed.index)).fillna("").astype(str).str.strip().ne("").sum()),
        "rows_with_clear_event_timestamps": int((timestamps.notna() & release_session.isin({"before_open", "intraday", "after_close"})).sum()),
        "rows_with_sector_benchmark": int(sector_benchmark.ne("").sum()),
        "likely_oos_predictions_min_train": int(max(0, len(reviewed) - int(min_train))),
        "execution_survivability_classification": "delayed-digestion",
        "execution_survivability_rationale": (
            "Item 1.05 filings can gap on headline risk, but impact estimates, operational recovery, customer notification scope, "
            "insurance offsets, and amendments often arrive after the first filing. This leaves a plausible delayed-digestion "
            "or slow-burn repricing window only after timestamp, duplicate, and public-awareness gates pass."
        ),
    }
    gates = {
        "reviewed_usable_events_80_min": metrics["reviewed_usable_rows"] >= 80,
        "reviewed_usable_events_100_preferred": metrics["reviewed_usable_rows"] >= 100,
        "item_105_events_50": metrics["item_105_rows"] >= 50,
        "material_incident_events_50": metrics["material_incident_rows"] >= 50,
        "operational_or_ransomware_events_20": metrics["operational_or_ransomware_rows"] >= 20,
        "market_cap_context_rows_40": metrics["rows_with_market_cap_context"] >= 40,
        "pre_event_context_rows_40": metrics["rows_with_pre_event_context"] >= 40,
        "clear_event_timestamps": metrics["rows_with_clear_event_timestamps"] >= metrics["reviewed_usable_rows"] and metrics["reviewed_usable_rows"] > 0,
        "duplicate_timestamp_audit_pass": metrics["duplicate_rows"] == 0,
        "hard_negative_review_pass": metrics["hard_negative_rows"] == 0 or metrics["reviewed_hard_negative_rows"] >= min(metrics["hard_negative_rows"], 30),
        "likely_oos_predictions_30": metrics["likely_oos_predictions_min_train"] >= 30,
        "sector_benchmark_controls_ready": metrics["rows_with_sector_benchmark"] >= metrics["reviewed_usable_rows"] and metrics["reviewed_usable_rows"] > 0,
    }
    if parser_errors is not None:
        ok_count = int(parser_errors.get("status", pd.Series(dtype=str)).astype(str).eq("ok").sum()) if not parser_errors.empty else 0
        audit_rows = int(len(parser_errors))
        audit_precision = ok_count / audit_rows if audit_rows else 0.0
        metrics["parser_audit_rows"] = audit_rows
        metrics["parser_audit_precision"] = float(audit_precision)
        hard_negative_false_material = False
        if {"gold_category", "actual_value", "status"}.issubset(parser_errors.columns):
            hard_negative_false_material = bool(
                (
                    parser_errors["gold_category"].astype(str).str.contains("hard_negative|generic|non_material|vendor_vulnerability", case=False, regex=True)
                    & parser_errors["actual_value"].astype(str).str.lower().isin({"material_cyber_incident", "ransomware", "business_interruption", "operational_disruption", "customer_data_breach"})
                    & parser_errors["status"].astype(str).ne("ok")
                ).any()
            )
        metrics["parser_hard_negative_false_material"] = hard_negative_false_material
        gates["parser_audit_pass"] = bool(audit_rows >= 60 and audit_precision >= 0.90 and not hard_negative_false_material)
    else:
        metrics["parser_audit_precision"] = "missing"
        gates["parser_audit_pass"] = False

    hard_gate_names = [gate for gate in gates if gate != "reviewed_usable_events_100_preferred"]
    blockers = [gate for gate in hard_gate_names if not gates.get(gate)]
    metrics["gates"] = {gate: bool(passed) for gate, passed in gates.items()}
    metrics["top_missing_fields_blocking_modeling"] = blockers
    if all(metrics["gates"].get(gate) for gate in hard_gate_names):
        metrics["decision"] = "model-ready"
        metrics["reason"] = "all hard non-modeling readiness gates pass; first-pass falsification may run with close-to-close and next-open outcomes"
    elif not metrics["gates"]["parser_audit_pass"]:
        metrics["decision"] = "parser not trusted"
        metrics["reason"] = "parser audit is missing or failing; stop before modeling"
    elif not metrics["gates"]["clear_event_timestamps"] or not metrics["gates"]["duplicate_timestamp_audit_pass"]:
        metrics["decision"] = "timestamp/duplicate audit insufficient"
        metrics["reason"] = "public timestamp, duplicate handling, or known-before-filing filters are not ready"
    elif not metrics["gates"]["market_cap_context_rows_40"] or not metrics["gates"]["pre_event_context_rows_40"] or not metrics["gates"]["sector_benchmark_controls_ready"]:
        metrics["decision"] = "context insufficient"
        metrics["reason"] = "size, run-up/volatility, or sector benchmark controls are under-covered"
    else:
        metrics["decision"] = "continue corpus buildout"
        metrics["reason"] = "readiness gates still failing: " + ", ".join(blockers)
    return metrics


def write_cybersecurity_incident_readiness_report(
    events_path: str | Path,
    out_path: str | Path,
    *,
    min_train: int = 40,
    source_documents_path: str | Path | None = None,
    parser_errors_path: str | Path | None = None,
) -> dict[str, object]:
    events = pd.read_csv(events_path)
    source_documents = pd.read_csv(source_documents_path) if source_documents_path else None
    parser_errors = pd.read_csv(parser_errors_path) if parser_errors_path else None
    summary = cybersecurity_incident_readiness_summary(
        events,
        min_train=min_train,
        source_documents=source_documents,
        parser_errors=parser_errors,
    )
    out = ensure_parent(out_path)
    lines = [
        "# Cybersecurity Material Incidents 8-K Readiness Report",
        "",
        "This is a non-modeling readiness report. It stops before first falsification unless every hard gate passes.",
        "",
        "## Verdict",
        "",
        f"- decision: {summary.get('decision')}",
        f"- reason: {summary.get('reason')}",
        "",
        "## Execution Survivability Gate",
        "",
        f"- classification: {summary.get('execution_survivability_classification')}",
        f"- rationale: {summary.get('execution_survivability_rationale', '')}",
        "- modeled outcomes required if eligible: close-to-close and next-open performance.",
        "",
        "## Required Counts",
        "",
    ]
    for key in [
        "source_documents_recovered",
        "parsed_event_rows",
        "reviewed_usable_rows",
        "item_105_rows",
        "material_incident_rows",
        "operational_or_ransomware_rows",
        "customer_data_exposure_rows",
        "no_material_impact_update_rows",
        "hard_negative_rows",
        "reviewed_hard_negative_rows",
        "duplicate_rows",
        "rows_with_market_cap_context",
        "rows_with_pre_event_context",
        "rows_with_source_evidence",
        "rows_with_clear_event_timestamps",
        "rows_with_sector_benchmark",
        "parser_audit_precision",
        "parser_hard_negative_false_material",
        "likely_oos_predictions_min_train",
    ]:
        if key in summary:
            lines.append(f"- {key}: {summary[key]}")
    lines.extend(["", "## Gates", ""])
    for gate, passed in (summary.get("gates", {}) or {}).items():
        lines.append(f"- {gate}: {'PASS' if passed else 'FAIL'}")
    lines.extend(["", "## Top Missing Fields Blocking Modeling", ""])
    for blocker in summary.get("top_missing_fields_blocking_modeling", []) or []:
        lines.append(f"- {blocker}")
    lines.extend(
        [
            "",
            "## Pre-Registered Candidate Hypotheses",
            "",
            "1. Material cyber incident with operational disruption is negative.",
            "2. Ransomware/business interruption is more negative than generic breach.",
            "3. Customer-data exposure is negative, especially in consumer/healthcare.",
            "4. No-material-impact amendment is weak/control.",
            "5. Legacy non-Item 1.05 disclosures are noisier than Item 1.05.",
            "",
            "Do not model until parser audit, timestamp/duplicate audit, context enrichment, and review gates pass. Do not tune thresholds after returns.",
        ]
    )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
