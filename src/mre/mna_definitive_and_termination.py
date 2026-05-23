from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Iterable

import numpy as np
import pandas as pd

from .events import make_event_template
from .paths import ensure_parent
from .prices import load_price_csv
from .source_docs import SOURCE_DOC_COLUMNS


MNA_DOMAIN = "mna_definitive_and_termination"

MNA_EVENT_TYPES = {
    "definitive_merger_agreement",
    "acquisition_announcement",
    "tender_offer",
    "acquisition_completion",
    "deal_termination",
    "regulatory_block",
    "financing_failure",
    "shareholder_vote_failure",
    "revised_terms",
    "termination_fee_event",
    "ordinary_material_agreement_control",
}

HARD_NEGATIVE_REASONS = {
    "ordinary_commercial_agreement",
    "licensing_agreement",
    "nonbinding_loi",
    "amendment_no_economic_change",
    "immaterial_asset_acquisition",
    "private_target_no_public_equity_reaction",
    "duplicate_event",
}

MNA_EXTRA_SOURCE_COLUMNS = [
    "target_ticker",
    "acquirer_ticker",
    "target_company_name",
    "acquirer_company_name",
    "target_or_acquirer_role",
    "deal_value",
    "deal_price_per_share",
    "payment_method_cash_stock_mixed",
    "premium_to_prior_close",
    "termination_fee",
    "regulatory_approval_required",
    "termination_reason",
    "completion_flag",
    "evidence",
    "confidence",
]

MNA_SOURCE_COLUMNS = SOURCE_DOC_COLUMNS + [c for c in MNA_EXTRA_SOURCE_COLUMNS if c not in SOURCE_DOC_COLUMNS]

MONEY_RE = re.compile(
    r"\$\s*(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<unit>billion|bn|million|mm|m|thousand|k)?",
    re.I,
)
PCT_RE = re.compile(r"(?P<num>\d+(?:\.\d+)?)\s*%")
PER_SHARE_RE = re.compile(r"\$\s*(?P<num>\d+(?:\.\d+)?)\s*(?:in cash\s*)?per share", re.I)

MNA_KEYWORDS = re.compile(
    r"\b(merger|acquisition|acquire|acquires|acquired|acquiring|tender offer|business combination|takeover|buyout)\b",
    re.I,
)
ORDINARY_AGREEMENT_RE = re.compile(
    r"\b(customer agreement|supply agreement|distribution agreement|license agreement|licensing agreement|collaboration agreement|manufacturing agreement|service agreement)\b",
    re.I,
)
NONBINDING_RE = re.compile(r"\b(non[- ]binding|letter of intent|loi|memorandum of understanding|mou)\b", re.I)
IMMATERIAL_ASSET_RE = re.compile(r"\b(immaterial asset|certain assets|portfolio of patents|single asset)\b", re.I)


@dataclass(frozen=True)
class MnaSourceDocument:
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
    target_ticker: str = ""
    acquirer_ticker: str = ""
    target_company_name: str = ""
    acquirer_company_name: str = ""
    target_or_acquirer_role: str = ""
    deal_value: float = np.nan
    deal_price_per_share: float = np.nan
    payment_method_cash_stock_mixed: str = ""
    premium_to_prior_close: float = np.nan
    termination_fee: float = np.nan
    regulatory_approval_required: bool = False
    termination_reason: str = ""
    completion_flag: bool = False
    evidence: str = ""
    confidence: float = np.nan


@dataclass(frozen=True)
class MnaFact:
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


def _norm_lower(value: object, default: str = "") -> str:
    return _norm(value, default=default).lower().strip()


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
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


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


def _normalize_ts(value: object) -> pd.Timestamp:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        raise ValueError(f"Could not parse event_time: {value!r}")
    out = pd.Timestamp(ts)
    if out.tzinfo is not None:
        try:
            out = out.tz_convert(None)
        except TypeError:
            out = out.tz_localize(None)
    return out


def load_mna_documents(manifest_path: str | Path) -> list[MnaSourceDocument]:
    manifest_path = Path(manifest_path)
    df = pd.read_csv(manifest_path)
    for col in MNA_SOURCE_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    docs: list[MnaSourceDocument] = []
    seen: set[str] = set()
    for i, row in df.iterrows():
        doc_id = _norm(row.get("source_doc_id"), default=f"mna_doc_{i+1:04d}")
        if doc_id in seen:
            raise ValueError(f"Duplicate source_doc_id: {doc_id}")
        seen.add(doc_id)
        ticker = _norm(row.get("ticker")).upper()
        if not ticker:
            raise ValueError(f"Missing ticker for source_doc_id={doc_id}")
        text = _norm(row.get("text")) or _read_text_from_path(row.get("path"), manifest_path.parent)
        if not text:
            raise ValueError(f"source_doc_id={doc_id} has neither inline text nor readable path")
        event_time = _normalize_ts(row.get("event_time"))
        event_id = _norm(row.get("event_id")) or f"{ticker}_mna_{event_time.strftime('%Y%m%d_%H%M')}_{doc_id}"
        docs.append(
            MnaSourceDocument(
                source_doc_id=doc_id,
                ticker=ticker,
                event_id=event_id,
                event_time=event_time,
                event_type=_norm_lower(row.get("event_type"), default="corporate_action"),
                event_subtype=_norm_lower(row.get("event_subtype"), default="mna_candidate"),
                release_session=_norm_lower(row.get("release_session"), default="unknown"),
                source_type=_norm_lower(row.get("source_type"), default="source_document"),
                source_url=_norm(row.get("source_url")),
                title=_norm(row.get("title"), default=f"{ticker} M&A source document"),
                text=text,
                path=_norm(row.get("path")),
                fiscal_period_end=_norm(row.get("fiscal_period_end")),
                sector_benchmark=_norm(row.get("sector_benchmark")).upper(),
                notes=_norm(row.get("notes")),
                target_ticker=_norm(row.get("target_ticker")).upper(),
                acquirer_ticker=_norm(row.get("acquirer_ticker")).upper(),
                target_company_name=_norm(row.get("target_company_name")),
                acquirer_company_name=_norm(row.get("acquirer_company_name")),
                target_or_acquirer_role=_norm_lower(row.get("target_or_acquirer_role")),
                deal_value=_to_float(row.get("deal_value")),
                deal_price_per_share=_to_float(row.get("deal_price_per_share")),
                payment_method_cash_stock_mixed=_norm_lower(row.get("payment_method_cash_stock_mixed")),
                premium_to_prior_close=_to_float(row.get("premium_to_prior_close")),
                termination_fee=_to_float(row.get("termination_fee")),
                regulatory_approval_required=_bool_value(row.get("regulatory_approval_required")),
                termination_reason=_norm_lower(row.get("termination_reason")),
                completion_flag=_bool_value(row.get("completion_flag")),
                evidence=_norm(row.get("evidence")),
                confidence=_to_float(row.get("confidence")),
            )
        )
    return docs


def _segments(text: str) -> list[str]:
    parts = []
    for raw in re.split(r"(?<!\d)[\.;!?](?!\d)|\n+", str(text or "")):
        seg = re.sub(r"\s+", " ", raw).strip()
        if 8 <= len(seg) <= 900:
            parts.append(seg)
    return parts


def _money_value(match: re.Match[str]) -> float:
    num = float(match.group("num").replace(",", ""))
    unit = (match.group("unit") or "").lower()
    if unit in {"billion", "bn"}:
        return num * 1_000_000_000.0
    if unit in {"million", "mm", "m"}:
        return num * 1_000_000.0
    if unit in {"thousand", "k"}:
        return num * 1_000.0
    return num


def _first_money_after(text: str, terms: Iterable[str]) -> tuple[float, str]:
    low = text.lower()
    for term in terms:
        pos = low.find(term)
        if pos >= 0:
            tail = text[pos : pos + 300]
            match = MONEY_RE.search(tail)
            if match:
                return _money_value(match), re.sub(r"\s+", " ", tail).strip()
    return np.nan, ""


def classify_mna_event_text(title: str, text: str, source_type: str = "") -> tuple[str, str]:
    blob = f"{title}\n{text}".lower()
    body = str(text or "").lower()
    if NONBINDING_RE.search(body) or NONBINDING_RE.search(blob):
        return "ordinary_material_agreement_control", "nonbinding_loi"
    if ORDINARY_AGREEMENT_RE.search(body) and not MNA_KEYWORDS.search(body):
        return "ordinary_material_agreement_control", "ordinary_commercial_agreement"
    if IMMATERIAL_ASSET_RE.search(body) and "substantially all" not in body:
        return "ordinary_material_agreement_control", "immaterial_asset_acquisition"
    if not MNA_KEYWORDS.search(blob):
        return "ordinary_material_agreement_control", "ordinary_commercial_agreement"

    termination = re.search(r"\b(terminat|abandon|cancel|withdraw)\w*\b", blob)
    if termination:
        if re.search(r"\b(regulatory|antitrust|ftc|doj|competition authority|blocked|injunction)\b", blob):
            return "regulatory_block", ""
        if re.search(r"\b(financing|debt commitment|funding)\b", blob):
            return "financing_failure", ""
        if re.search(r"\b(shareholder|stockholder).{0,40}\b(vote|approval|reject|fail)\b", blob):
            return "shareholder_vote_failure", ""
        if "termination fee" in blob:
            return "termination_fee_event", ""
        return "deal_termination", ""
    if re.search(r"\b(completed|closed|consummated)\b.{0,80}\b(acquisition|merger|tender offer|business combination)\b", blob):
        return "acquisition_completion", ""
    if "tender offer" in blob:
        return "tender_offer", ""
    if re.search(r"\b(revised|amended|increased|decreased|sweetened|reduced)\b.{0,80}\b(offer|consideration|merger agreement|deal)\b", blob):
        return "revised_terms", ""
    if "agreement and plan of merger" in blob or re.search(r"\bdefinitive\b.{0,80}\b(merger agreement|agreement to acquire|acquisition agreement)\b", blob):
        return "definitive_merger_agreement", ""
    return "acquisition_announcement", ""


def _payment_method(text: str, fallback: str = "") -> str:
    if fallback:
        return fallback
    low = text.lower()
    cash = bool(re.search(r"\ball[- ]cash\b|\bin cash\b", low))
    stock = bool(re.search(r"\ball[- ]stock\b|\bstock consideration\b|\bshares of\b|\bexchange ratio\b", low))
    if cash and stock:
        return "mixed"
    if cash:
        return "cash"
    if stock:
        return "stock"
    return "unknown"


def _termination_reason(event_type: str, text: str, fallback: str = "") -> str:
    if fallback:
        return fallback
    low = text.lower()
    if event_type == "regulatory_block":
        return "regulatory_block"
    if event_type == "financing_failure":
        return "financing_failure"
    if event_type == "shareholder_vote_failure":
        return "shareholder_vote_failure"
    if "mutual" in low and "terminat" in low:
        return "mutual_termination"
    if "superior proposal" in low:
        return "superior_proposal"
    if "termination fee" in low:
        return "termination_fee_event"
    return "unknown" if "terminat" in low else ""


def _fact(doc: MnaSourceDocument, name: str, value: object, unit: str, evidence: str, confidence: float, method: str) -> MnaFact:
    return MnaFact(
        source_doc_id=doc.source_doc_id,
        event_id=doc.event_id,
        ticker=doc.ticker,
        event_time=doc.event_time.isoformat(),
        fact_name=name,
        value=value,
        unit=unit,
        evidence_text=evidence[:500],
        confidence=float(confidence),
        parse_method=method,
        source_type=doc.source_type,
        source_url=doc.source_url,
    )


def parse_mna_document(doc: MnaSourceDocument) -> list[MnaFact]:
    text = f"{doc.title}\n{doc.text}"
    event_type, hard_negative_reason = classify_mna_event_text(doc.title, doc.text, doc.source_type)
    confidence = 0.86 if hard_negative_reason else 0.78
    if event_type in {"definitive_merger_agreement", "deal_termination", "regulatory_block", "financing_failure", "shareholder_vote_failure"}:
        confidence = 0.86

    deal_value = doc.deal_value
    deal_value_evidence = doc.evidence
    if pd.isna(deal_value):
        deal_value, deal_value_evidence = _first_money_after(
            text,
            ["transaction valued at", "enterprise value", "equity value", "deal value", "valued at", "for approximately"],
        )
    price = doc.deal_price_per_share
    price_evidence = doc.evidence
    if pd.isna(price):
        match = PER_SHARE_RE.search(text)
        if match:
            price = float(match.group("num"))
            price_evidence = match.group(0)
    premium = doc.premium_to_prior_close
    premium_evidence = doc.evidence
    if pd.isna(premium):
        for seg in _segments(text):
            if "premium" in seg.lower():
                match = PCT_RE.search(seg)
                if match:
                    premium = float(match.group("num")) / 100.0
                    premium_evidence = seg
                    break
    termination_fee = doc.termination_fee
    termination_fee_evidence = doc.evidence
    if pd.isna(termination_fee):
        termination_fee, termination_fee_evidence = _first_money_after(text, ["termination fee", "break-up fee", "breakup fee"])

    payment = _payment_method(text, doc.payment_method_cash_stock_mixed)
    regulatory = doc.regulatory_approval_required or bool(re.search(r"\b(regulatory approval|antitrust|HSR Act|FTC|DOJ)\b", text, re.I))
    term_reason = _termination_reason(event_type, text, doc.termination_reason)
    completion = doc.completion_flag or event_type == "acquisition_completion"
    target = doc.target_ticker
    acquirer = doc.acquirer_ticker
    role = doc.target_or_acquirer_role
    if not role and doc.ticker:
        if target and doc.ticker == target:
            role = "target"
        elif acquirer and doc.ticker == acquirer:
            role = "acquirer"
        else:
            role = "unknown"

    facts = [
        _fact(doc, "mna_event_type", event_type, "category", doc.title or text[:160], confidence, "rule"),
        _fact(doc, "hard_negative_flag", bool(hard_negative_reason), "bool", hard_negative_reason or doc.title, 0.90 if hard_negative_reason else 0.75, "rule"),
        _fact(doc, "hard_negative_reason", hard_negative_reason, "category", hard_negative_reason or doc.title, 0.90 if hard_negative_reason else 0.75, "rule"),
        _fact(doc, "target_ticker", target, "ticker", doc.evidence or doc.title, 0.95 if target else 0.20, "manifest"),
        _fact(doc, "acquirer_ticker", acquirer, "ticker", doc.evidence or doc.title, 0.95 if acquirer else 0.20, "manifest"),
        _fact(doc, "target_or_acquirer_role", role or "unknown", "category", doc.evidence or doc.title, 0.90 if role and role != "unknown" else 0.30, "manifest"),
        _fact(doc, "payment_method_cash_stock_mixed", payment, "category", text[:240], 0.78 if payment != "unknown" else 0.35, "rule"),
        _fact(doc, "regulatory_approval_required", bool(regulatory), "bool", text[:240], 0.78, "rule"),
        _fact(doc, "termination_reason", term_reason, "category", text[:240], 0.82 if term_reason else 0.30, "rule"),
        _fact(doc, "completion_flag", bool(completion), "bool", text[:240], 0.82, "rule"),
    ]
    if pd.notna(deal_value):
        facts.append(_fact(doc, "deal_value", deal_value, "usd", deal_value_evidence or text[:240], 0.78, "rule_or_manifest"))
    if pd.notna(price):
        facts.append(_fact(doc, "deal_price_per_share", price, "usd_per_share", price_evidence or text[:240], 0.82, "rule_or_manifest"))
    if pd.notna(premium):
        facts.append(_fact(doc, "premium_to_prior_close", premium, "ratio", premium_evidence or text[:240], 0.78, "rule_or_manifest"))
    if pd.notna(termination_fee):
        facts.append(_fact(doc, "termination_fee", termination_fee, "usd", termination_fee_evidence or text[:240], 0.78, "rule_or_manifest"))
    return facts


def pivot_mna_facts(facts: pd.DataFrame, out_path: str | Path | None = None, *, min_confidence: float = 0.70) -> pd.DataFrame:
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
            ranked = group.sort_values(["confidence"], ascending=False).drop_duplicates("fact_name")
            for _, fact in ranked.iterrows():
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


def mna_features_to_events(features: pd.DataFrame, out_path: str | Path) -> pd.DataFrame:
    rows: list[dict] = []
    for _, row in features.iterrows():
        event_type = _norm(row.get("mna_event_type"), "ordinary_material_agreement_control")
        target = _norm(row.get("target_ticker")).upper()
        acquirer = _norm(row.get("acquirer_ticker")).upper()
        role = _norm_lower(row.get("target_or_acquirer_role"), "unknown")
        reaction_ticker = target or acquirer or _norm(row.get("ticker")).upper()
        hard_negative = _bool_value(row.get("hard_negative_flag"))
        direction = "unknown"
        if event_type in {"definitive_merger_agreement", "acquisition_announcement", "tender_offer"} and role == "target":
            direction = "positive"
        elif event_type in {"deal_termination", "regulatory_block", "financing_failure", "shareholder_vote_failure"} and role == "target":
            direction = "negative"
        rows.append(
            {
                "event_id": row["event_id"],
                "ticker": reaction_ticker,
                "event_time": row["event_time"],
                "event_type": "corporate_action",
                "summary": f"{reaction_ticker} {event_type.replace('_', ' ')} M&A candidate.",
                "event_subtype": event_type,
                "event_family": MNA_DOMAIN,
                "source_type": row.get("source_type", "source_document"),
                "source_url": row.get("source_url", ""),
                "release_session": "unknown",
                "expectedness": "unknown",
                "surprise_direction": direction,
                "surprise_magnitude": "unknown",
                "materiality": 0.1 if hard_negative else 0.7,
                "sector_benchmark": "",
                "notes": "M&A parser candidate; review target/acquirer role, deal economics, public timestamp, duplicate status, and execution survivability before modeling.",
                "review_status": "rejected" if hard_negative else "unreviewed",
                "label_quality": "hard_negative" if hard_negative else "machine_candidate",
                "source_doc_ids": row.get("source_doc_ids", ""),
                "evidence_status": "source_backed",
                **{c: row.get(c, "") for c in features.columns if c not in {"ticker", "event_id", "event_time", "source_type", "source_url", "source_doc_ids"}},
            }
        )
    make_event_template(out_path, rows)
    return pd.read_csv(out_path)


def parse_mna_manifest(
    documents_path: str | Path,
    facts_out: str | Path,
    features_out: str | Path,
    events_out: str | Path,
    *,
    min_confidence: float = 0.0,
    usable_confidence: float = 0.70,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    docs = load_mna_documents(documents_path)
    rows: list[dict] = []
    for doc in docs:
        for fact in parse_mna_document(doc):
            if fact.confidence >= min_confidence:
                rows.append(fact.to_dict())
    facts = pd.DataFrame(rows)
    if not facts.empty:
        facts = facts.sort_values(["ticker", "event_time", "event_id", "fact_name"]).reset_index(drop=True)
    ensure_parent(facts_out)
    facts.to_csv(facts_out, index=False)
    features = pivot_mna_facts(facts, features_out, min_confidence=usable_confidence)
    events = mna_features_to_events(features, events_out)
    return facts, features, events


def validate_mna_parser(
    facts: pd.DataFrame,
    gold: pd.DataFrame,
    *,
    out_errors: str | Path | None = None,
    tolerance: float = 0.01,
) -> tuple[pd.DataFrame, dict[str, object]]:
    if gold.empty:
        errors = pd.DataFrame(columns=["event_id", "fact_name", "status", "expected_value", "actual_value"])
        return errors, {"gold_rows": 0, "correct_rows": 0, "row_accuracy": 0.0, "parser_audit_pass": False}
    if "gold_review_status" in gold.columns:
        reviewed = gold["gold_review_status"].fillna("").astype(str).str.lower().isin({"reviewed", "approved", "curated"})
        if not reviewed.all():
            errors = gold.copy()
            errors["status"] = "gold_not_reviewed"
            report = {
                "status": "gold_set_requires_human_review",
                "gold_rows": int(len(gold)),
                "correct_rows": 0,
                "row_accuracy": 0.0,
                "audit_gate_results": {"gold_set_human_reviewed": False},
                "parser_audit_pass": False,
            }
            if out_errors:
                ensure_parent(out_errors)
                errors.to_csv(out_errors, index=False)
            return errors, report

    lookup = {}
    if not facts.empty:
        ranked = facts.copy()
        ranked["confidence"] = pd.to_numeric(ranked.get("confidence", 0.0), errors="coerce").fillna(0.0)
        for _, row in ranked.sort_values("confidence", ascending=False).drop_duplicates(["event_id", "fact_name"]).iterrows():
            lookup[(str(row["event_id"]), str(row["fact_name"]))] = row
    rows = []
    for _, expected in gold.iterrows():
        event_id = str(expected.get("event_id", ""))
        fact_name = str(expected.get("fact_name", ""))
        expected_present = _bool_value(expected.get("expected_present", True))
        actual = lookup.get((event_id, fact_name))
        actual_value = actual.get("value") if actual is not None else ""
        expected_value = expected.get("expected_value", "")
        status = "ok"
        if not expected_present and actual is not None:
            status = "false_positive"
        elif expected_present and actual is None:
            status = "missing"
        elif expected_present:
            exp_num = _to_float(expected_value)
            act_num = _to_float(actual_value)
            if pd.notna(exp_num) and pd.notna(act_num):
                denom = max(abs(exp_num), 1.0)
                status = "ok" if abs(exp_num - act_num) / denom <= tolerance else "wrong_value"
            else:
                status = "ok" if _norm(expected_value).lower() == _norm(actual_value).lower() else "wrong_value"
        rows.append(
            {
                "event_id": event_id,
                "fact_name": fact_name,
                "status": status,
                "expected_value": expected_value,
                "actual_value": actual_value,
                "expected_present": expected_present,
            }
        )
    errors = pd.DataFrame(rows)
    ok = int((errors["status"] == "ok").sum())
    audit_rows = int(len(errors))
    by_fact = {}
    for fact_name, group in errors.groupby("fact_name"):
        by_fact[fact_name] = {"rows": int(len(group)), "accuracy": float((group["status"] == "ok").mean())}
    gates = {
        "gold_set_60_rows": audit_rows >= 60,
        "row_accuracy_90": (ok / audit_rows if audit_rows else 0.0) >= 0.90,
        "event_type_precision_90": by_fact.get("mna_event_type", {}).get("accuracy", 0.0) >= 0.90,
        "hard_negative_precision_95": by_fact.get("hard_negative_flag", {}).get("accuracy", 0.0) >= 0.95,
        "role_and_terms_precision_90": min(
            by_fact.get("target_or_acquirer_role", {}).get("accuracy", 0.0),
            by_fact.get("payment_method_cash_stock_mixed", {"accuracy": 1.0}).get("accuracy", 1.0),
        )
        >= 0.90,
    }
    report = {
        "gold_rows": audit_rows,
        "correct_rows": ok,
        "row_accuracy": float(ok / audit_rows) if audit_rows else 0.0,
        "by_fact": by_fact,
        "audit_gate_results": gates,
        "parser_audit_pass": bool(all(gates.values())),
    }
    if out_errors:
        ensure_parent(out_errors)
        errors.to_csv(out_errors, index=False)
    return errors, report


def audit_mna_timestamps_and_duplicates(events: pd.DataFrame, out_path: str | Path | None = None) -> tuple[pd.DataFrame, dict[str, object]]:
    out = events.copy()
    if out.empty:
        return out, {"rows": 0, "gates": {"no_duplicate_events": False, "clear_public_timestamps": False}}
    for col in ["target_ticker", "acquirer_ticker", "mna_event_type", "deal_price_per_share", "source_url", "release_session"]:
        if col not in out.columns:
            out[col] = ""
    event_date = pd.to_datetime(out["event_time"], errors="coerce").dt.date.astype(str)
    deal_price = pd.to_numeric(out["deal_price_per_share"], errors="coerce").round(4).astype(str)
    keys = (
        out["target_ticker"].fillna("").astype(str).str.upper()
        + "|"
        + out["acquirer_ticker"].fillna("").astype(str).str.upper()
        + "|"
        + out["mna_event_type"].fillna("").astype(str)
        + "|"
        + event_date
        + "|"
        + deal_price
    )
    out["_duplicate_key"] = keys
    out["_event_time_sort"] = pd.to_datetime(out["event_time"], errors="coerce")
    out = out.sort_values(["_duplicate_key", "_event_time_sort", "event_id"]).reset_index(drop=True)
    out["duplicate_status"] = "primary"
    out.loc[out.duplicated("_duplicate_key", keep="first"), "duplicate_status"] = "duplicate"
    session = out["release_session"].fillna("unknown").astype(str).str.lower()
    out["timestamp_suitable_flag"] = session.isin({"before_open", "intraday", "after_close"})
    out["public_awareness_evidence_status"] = np.where(out["timestamp_suitable_flag"], "public_timestamp_present", "timestamp_needs_review")
    out = out.drop(columns=["_duplicate_key", "_event_time_sort"])
    primary_share = float((out["duplicate_status"] == "primary").mean()) if len(out) else 0.0
    clear_rows = int(out["timestamp_suitable_flag"].sum())
    summary = {
        "rows": int(len(out)),
        "primary_rows": int((out["duplicate_status"] == "primary").sum()),
        "duplicate_rows": int((out["duplicate_status"] == "duplicate").sum()),
        "clear_timestamp_rows": clear_rows,
        "gates": {
            "no_duplicate_events": bool(primary_share >= 0.95),
            "clear_public_timestamps": bool(clear_rows >= 80),
        },
    }
    if out_path:
        ensure_parent(out_path)
        out.to_csv(out_path, index=False)
    return out, summary


def _anchor_price(prices: pd.DataFrame, event_time: object, release_session: object) -> tuple[pd.Timestamp | None, float]:
    ts = pd.to_datetime(event_time, errors="coerce")
    if pd.isna(ts):
        return None, np.nan
    ts = ts.tz_localize(None) if getattr(ts, "tzinfo", None) else ts
    date = ts.normalize()
    include_same_day = _norm_lower(release_session) in {"after_close", "intraday", "market_hours", "unknown", ""}
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
    return end / start - 1.0 if pd.notna(start) and pd.notna(end) and start else np.nan


def _lookup_context(row: pd.Series, context: pd.DataFrame, ticker_col: str, value_col: str) -> float:
    if context.empty:
        return np.nan
    event_id = _norm(row.get("event_id"))
    if "event_id" in context.columns:
        matched = context[context["event_id"].astype(str) == event_id]
        if not matched.empty:
            return _to_float(matched.iloc[0].get(value_col))
    ticker = _norm(row.get(ticker_col)).upper() or _norm(row.get("ticker")).upper()
    if not ticker or "ticker" not in context.columns:
        return np.nan
    subset = context[context["ticker"].astype(str).str.upper() == ticker].copy()
    if subset.empty:
        return np.nan
    if "asof_date" in subset.columns:
        subset["asof_date"] = pd.to_datetime(subset["asof_date"], errors="coerce")
        event_time = pd.to_datetime(row.get("event_time"), errors="coerce")
        if pd.notna(event_time):
            subset = subset[subset["asof_date"] <= event_time]
        subset = subset.sort_values("asof_date", ascending=False)
    return _to_float(subset.iloc[0].get(value_col)) if not subset.empty else np.nan


def enrich_mna_context(
    events_path: str | Path,
    prices_dir: str | Path,
    out_path: str | Path,
    *,
    benchmark_ticker: str = "SPY",
    market_caps_path: str | Path | None = None,
) -> pd.DataFrame:
    events = pd.read_csv(events_path)
    market_caps = pd.read_csv(market_caps_path) if market_caps_path and Path(market_caps_path).exists() else pd.DataFrame()
    price_cache: dict[str, pd.DataFrame] = {}
    try:
        benchmark_prices = load_price_csv(prices_dir, benchmark_ticker.upper())
    except FileNotFoundError:
        benchmark_prices = pd.DataFrame()
    rows = []
    for _, row in events.iterrows():
        out = row.to_dict()
        ticker = _norm(row.get("ticker")).upper()
        status: list[str] = []
        try:
            prices = price_cache.setdefault(ticker, load_price_csv(prices_dir, ticker)) if ticker else pd.DataFrame()
        except FileNotFoundError:
            prices = pd.DataFrame()
            status.append("missing_reaction_ticker_prices")
        if benchmark_prices.empty:
            status.append("missing_benchmark_prices")
        anchor, close = _anchor_price(prices, row.get("event_time"), row.get("release_session")) if not prices.empty else (None, np.nan)
        out["price_anchor_date"] = anchor.date().isoformat() if anchor is not None else ""
        out["last_close_before_event"] = close
        target_mc = _to_float(row.get("target_market_cap_before_event"))
        acquirer_mc = _to_float(row.get("acquirer_market_cap_before_event"))
        if pd.isna(target_mc):
            target_mc = _lookup_context(row, market_caps, "target_ticker", "target_market_cap_before_event")
            if pd.isna(target_mc):
                target_mc = _lookup_context(row, market_caps, "target_ticker", "market_cap_before_event")
        if pd.isna(acquirer_mc):
            acquirer_mc = _lookup_context(row, market_caps, "acquirer_ticker", "acquirer_market_cap_before_event")
            if pd.isna(acquirer_mc):
                acquirer_mc = _lookup_context(row, market_caps, "acquirer_ticker", "market_cap_before_event")
        out["target_market_cap_before_event"] = target_mc
        out["acquirer_market_cap_before_event"] = acquirer_mc
        deal_value = _to_float(row.get("deal_value"))
        out["deal_value_pct_acquirer_market_cap"] = deal_value / acquirer_mc if pd.notna(deal_value) and pd.notna(acquirer_mc) and acquirer_mc else np.nan
        premium = _to_float(row.get("premium_to_prior_close"))
        out["premium_pct"] = premium * 100.0 if pd.notna(premium) and abs(premium) <= 2 else premium
        for window in (20, 60):
            stock_ret = _window_return(prices, anchor, window) if not prices.empty else np.nan
            bench_anchor, _ = _anchor_price(benchmark_prices, row.get("event_time"), row.get("release_session")) if not benchmark_prices.empty else (None, np.nan)
            bench_ret = _window_return(benchmark_prices, bench_anchor, window) if not benchmark_prices.empty else np.nan
            out[f"pre_event_return_{window}d"] = stock_ret
            out[f"pre_event_benchmark_return_{window}d"] = bench_ret
            out[f"pre_event_market_adjusted_return_{window}d"] = stock_ret - bench_ret if pd.notna(stock_ret) and pd.notna(bench_ret) else np.nan
        if not prices.empty and anchor is not None:
            idx_matches = prices.index[prices["date"] == anchor].tolist()
            idx = idx_matches[-1] if idx_matches else None
            out["liquidity"] = float(prices.iloc[max(0, idx - 20) : idx + 1]["volume"].mean()) if idx is not None and "volume" in prices.columns else np.nan
        else:
            out["liquidity"] = np.nan
        if pd.isna(out["deal_value_pct_acquirer_market_cap"]):
            status.append("missing_deal_value_pct_acquirer_market_cap")
        if pd.isna(out["pre_event_market_adjusted_return_20d"]):
            status.append("missing_pre_event_runup")
        out["mna_context_status"] = "ok" if not status else ";".join(sorted(set(status)))
        rows.append(out)
    enriched = pd.DataFrame(rows)
    ensure_parent(out_path)
    enriched.to_csv(out_path, index=False)
    return enriched


def classify_execution_survivability(row: dict | pd.Series) -> tuple[str, str, bool]:
    event_type = _norm_lower(row.get("mna_event_type", row.get("event_subtype", "")))
    role = _norm_lower(row.get("target_or_acquirer_role"), "unknown")
    reason = _norm_lower(row.get("termination_reason"))
    if event_type in {"definitive_merger_agreement", "acquisition_announcement", "tender_offer"} and role == "target":
        return (
            "immediate-gap",
            "Target deal announcements usually capitalize most premium information at the first realistic print; tradeability after next open requires merger-spread or competing-bid setup evidence.",
            False,
        )
    if event_type in {"deal_termination", "regulatory_block", "financing_failure", "shareholder_vote_failure", "revised_terms"}:
        if event_type == "revised_terms" or reason in {"regulatory_block", "financing_failure", "shareholder_vote_failure"}:
            return (
                "delayed-digestion",
                "Breaks, blocks, financing failures, and revised terms can require reassessment of standalone value, break fees, financing, and regulatory path after the first print.",
                True,
            )
        return (
            "slow-burn repricing",
            "Mutual or ambiguous terminations may reprice through follow-on analyst and holder reassessment, but need next-open evidence before any tradable claim.",
            True,
        )
    if event_type == "acquisition_completion":
        return (
            "explanation-only",
            "Completion is normally expected once the spread collapses; it is useful for audit labels but weak as a first-entry trade.",
            False,
        )
    if event_type == "ordinary_material_agreement_control":
        return (
            "explanation-only",
            "Ordinary agreements and hard negatives are controls, not M&A reaction candidates.",
            False,
        )
    return (
        "pre-event setup",
        "Acquirer-side or ambiguous-role events may be tradeable only with pre-event setup features such as spread, financing exposure, and deal-size context.",
        False,
    )


def execution_survivability_summary(events: pd.DataFrame) -> dict[str, object]:
    if events.empty:
        return {"rows": 0, "gate_pass": False, "reason": "no event rows", "class_counts": {}}
    classified = [classify_execution_survivability(row) for _, row in events.iterrows()]
    classes = [c[0] for c in classified]
    plaus = [c[2] for c in classified]
    class_counts = pd.Series(classes).value_counts().to_dict()
    has_next_open = {"next_open_abnormal_return", "close_to_close_abnormal_return"}.issubset(events.columns)
    stress_cols = {"stress_25bps_next_open", "stress_50bps_next_open", "stress_100bps_next_open"}
    has_stress = stress_cols.issubset(events.columns)
    plausible_rows = int(sum(plaus))
    gate_pass = bool(plausible_rows >= 40 and has_next_open and has_stress)
    if not has_next_open:
        reason = "missing close-to-close versus next-open behavior; close-to-close effects cannot be treated as tradable"
    elif not has_stress:
        reason = "missing 25/50/100 bps next-open execution stress"
    elif plausible_rows < 40:
        reason = "too few events classified as plausibly tradeable after first realistic entry"
    else:
        reason = "execution survivability evidence present"
    return {
        "rows": int(len(events)),
        "class_counts": {str(k): int(v) for k, v in class_counts.items()},
        "plausibly_tradeable_after_first_entry_rows": plausible_rows,
        "has_close_to_close_and_next_open": bool(has_next_open),
        "has_25_50_100_bps_stress": bool(has_stress),
        "gate_pass": gate_pass,
        "reason": reason,
    }


def mna_readiness_summary(
    events: pd.DataFrame,
    *,
    source_documents: pd.DataFrame | None = None,
    min_train: int = 40,
    parser_errors: pd.DataFrame | None = None,
) -> dict[str, object]:
    if events.empty:
        exec_summary = execution_survivability_summary(events)
        gates = {
            "parser_audit_pass": False,
            "reviewed_usable_events_100_min": False,
            "target_announcement_events_40": False,
            "termination_or_break_events_30": False,
            "role_coverage_80": False,
            "deal_terms_context_rows_50": False,
            "clear_public_timestamps_80": False,
            "primary_duplicate_rows_95pct": False,
            "likely_oos_predictions_30": False,
            "execution_survivability_gate": False,
        }
        return {
            "decision": "continue corpus buildout",
            "reason": "no parsed event rows",
            "parsed_event_rows": 0,
            "execution_survivability": exec_summary,
            "gates": gates,
            "top_missing_fields_blocking_modeling": list(gates),
        }
    review = events.get("review_status", pd.Series("", index=events.index)).fillna("").astype(str).str.lower()
    usable = events[~review.isin({"rejected", "drop", "dropped"})].copy()
    reviewed = usable[review.loc[usable.index].isin({"reviewed", "curated", "approved"})].copy()
    event_type = usable.get("mna_event_type", usable.get("event_subtype", pd.Series("", index=usable.index))).fillna("").astype(str).str.lower()
    role = usable.get("target_or_acquirer_role", pd.Series("", index=usable.index)).fillna("").astype(str).str.lower()
    target_ann = event_type.isin({"definitive_merger_agreement", "acquisition_announcement", "tender_offer"}) & role.eq("target")
    terminations = event_type.isin({"deal_termination", "regulatory_block", "financing_failure", "shareholder_vote_failure"})
    clear_ts = usable.get("release_session", pd.Series("unknown", index=usable.index)).fillna("unknown").astype(str).str.lower().ne("unknown")
    primary = usable.get("duplicate_status", pd.Series("primary", index=usable.index)).fillna("primary").astype(str).str.lower().eq("primary")
    parser_pass = False
    parser_accuracy = 0.0
    parser_rows = 0
    if parser_errors is not None:
        parser_rows = int(len(parser_errors))
        parser_accuracy = float((parser_errors.get("status", pd.Series(dtype=str)) == "ok").mean()) if parser_rows else 0.0
        parser_pass = bool(parser_rows >= 60 and parser_accuracy >= 0.90)
    exec_summary = execution_survivability_summary(usable)
    source_rows = int(len(source_documents)) if source_documents is not None else np.nan
    context_rows = int(
        usable.get("deal_value_pct_acquirer_market_cap", pd.Series(index=usable.index, dtype=float)).notna().sum()
        + usable.get("premium_pct", pd.Series(index=usable.index, dtype=float)).notna().sum()
    )
    metrics: dict[str, object] = {
        "source_documents_recovered": source_rows,
        "parsed_event_rows": int(len(events)),
        "reviewed_usable_rows": int(len(reviewed)),
        "target_announcement_rows": int(target_ann.sum()),
        "termination_or_break_rows": int(terminations.sum()),
        "rows_with_role": int(role.isin({"target", "acquirer"}).sum()),
        "rows_with_payment_method": int(usable.get("payment_method_cash_stock_mixed", pd.Series("", index=usable.index)).fillna("").astype(str).str.lower().isin({"cash", "stock", "mixed"}).sum()),
        "rows_with_context_terms": context_rows,
        "clear_timestamp_rows": int(clear_ts.sum()),
        "primary_duplicate_rows": int(primary.sum()),
        "likely_oos_predictions_min_train": int(max(0, len(reviewed) - int(min_train))),
        "parser_audit_rows": parser_rows,
        "parser_audit_accuracy": parser_accuracy,
        "execution_survivability": exec_summary,
    }
    gates = {
        "parser_audit_pass": parser_pass,
        "reviewed_usable_events_100_min": int(len(reviewed)) >= 100,
        "target_announcement_events_40": int(target_ann.sum()) >= 40,
        "termination_or_break_events_30": int(terminations.sum()) >= 30,
        "role_coverage_80": metrics["rows_with_role"] >= 80,
        "deal_terms_context_rows_50": context_rows >= 50,
        "clear_public_timestamps_80": int(clear_ts.sum()) >= 80,
        "primary_duplicate_rows_95pct": (float(primary.mean()) if len(primary) else 0.0) >= 0.95,
        "likely_oos_predictions_30": metrics["likely_oos_predictions_min_train"] >= 30,
        "execution_survivability_gate": bool(exec_summary.get("gate_pass")),
    }
    blockers = [gate for gate, passed in gates.items() if not passed]
    metrics["gates"] = gates
    metrics["top_missing_fields_blocking_modeling"] = blockers
    if not gates["parser_audit_pass"]:
        decision = "parser not trusted"
        reason = "parser audit is missing or failing"
    elif not gates["clear_public_timestamps_80"]:
        decision = "timestamp/public-awareness insufficient"
        reason = "too few rows have exact public release sessions"
    elif not gates["execution_survivability_gate"]:
        decision = "execution survivability not established"
        reason = str(exec_summary.get("reason"))
    elif all(gates.values()):
        decision = "model-ready"
        reason = "all non-modeling and execution survivability gates pass"
    else:
        decision = "continue corpus buildout"
        reason = "reviewed usable counts, event slices, or context fields are below modeling gates"
    metrics["decision"] = decision
    metrics["reason"] = reason
    return metrics


def write_mna_final_report(
    out_path: str | Path,
    *,
    readiness: dict[str, object],
    source_manifest_path: str | Path | None = None,
    parser_errors_path: str | Path | None = None,
) -> Path:
    exec_summary = readiness.get("execution_survivability", {}) or {}
    lines = [
        "# M&A Definitive Agreements And Terminations Final Report",
        "",
        f"Verdict: {readiness.get('decision', 'unknown')}.",
        "",
        f"Stop point: {readiness.get('reason', 'unknown')}. No modeling is permitted until readiness and execution survivability pass.",
        "",
        "## Domain",
        "",
        "- Domain name: mna_definitive_and_termination",
        "- Research question: Do definitive M&A announcements and deal terminations produce abnormal returns after controlling for role, premium, payment method, deal size, and termination reason?",
        "- Primary sources: SEC 8-K Items 1.01, 1.02, 2.01; merger exhibits; Exhibit 99 press releases; S-4/proxy only when needed.",
        "- Benchmarks: SPY primary; sector ETF only when available.",
        "",
        "## Lifecycle Status",
        "",
        "- scaffold/source discovery/parser: implemented for manifest-driven SEC/press-release documents",
        "- review queue: machine candidates are unreviewed; hard negatives are rejected",
        "- parser audit: required before modeling",
        "- context enrichment: target/acquirer market cap, deal-value scale, premium, run-up, and liquidity scaffolding implemented",
        "- timestamp and duplicate audit: implemented; exact public sessions required",
        "- readiness gates: evaluated below",
        "- first falsification/fresh confirmation/final signal verdict: not reached",
        "",
        "## Execution Survivability Gate",
        "",
        f"- gate_pass: {exec_summary.get('gate_pass', False)}",
        f"- reason: {exec_summary.get('reason', 'not evaluated')}",
        f"- class_counts: {exec_summary.get('class_counts', {})}",
        f"- plausibly_tradeable_after_first_entry_rows: {exec_summary.get('plausibly_tradeable_after_first_entry_rows', 0)}",
        "",
        "Classification policy:",
        "",
        "- Target deal announcements/tender offers: immediate-gap. They may explain close-to-close abnormal returns, but usually are not tradable after the first realistic next-open entry unless merger-spread or competing-bid setup evidence exists.",
        "- Terminations, regulatory blocks, financing failures, shareholder-vote failures, and revised terms: delayed-digestion or slow-burn repricing. They may remain tradable because standalone value, break fees, financing, litigation, and regulatory path can be reassessed after the first print.",
        "- Completion events: explanation-only unless there is an independently auditable residual spread or unexpected close timing.",
        "- Any modeled pass must report both close-to-close and next-open behavior with 25/50/100 bps execution stress. A close-to-close explanatory effect is not a tradable result if next-open fails.",
        "",
        "## Readiness Gates",
        "",
    ]
    for gate, passed in (readiness.get("gates", {}) or {}).items():
        lines.append(f"- {gate}: {'PASS' if passed else 'FAIL'}")
    lines.extend(["", "## Summary Counts", ""])
    for key, value in readiness.items():
        if key in {"gates", "top_missing_fields_blocking_modeling", "execution_survivability", "decision", "reason"}:
            continue
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Blocking Items", ""])
    for blocker in readiness.get("top_missing_fields_blocking_modeling", []) or []:
        lines.append(f"- {blocker}")
    lines.extend(
        [
            "",
            "## Hard Negatives",
            "",
            "- Ordinary commercial agreements, licensing/collaboration deals, non-binding LOIs/MOUs, amendments with no economic change, immaterial asset acquisitions, private targets without public-equity reaction, and duplicate press-release/8-K/proxy rows are excluded from model eligibility.",
            "",
            "## Pre-Registered Hypotheses",
            "",
            "1. Definitive acquisition announcement is positive for target.",
            "2. Deal termination is negative for target.",
            "3. Acquirer reaction depends on deal size and payment method.",
            "4. Regulatory block/financing failure termination is more negative than mutual termination.",
            "5. Completion event itself is weaker if expected.",
            "",
            "## Artifacts",
            "",
            f"- source manifest: {source_manifest_path or 'not built in this pass'}",
            f"- parser errors: {parser_errors_path or 'not available'}",
        ]
    )
    out = ensure_parent(out_path)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
