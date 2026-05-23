from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .events import OPTIONAL_EVENT_COLUMNS_WITH_DEFAULTS, REQUIRED_EVENT_COLUMNS, load_events
from .paths import ensure_parent

# Domain-specific feature schemas.  These are deliberately small and explicit:
# a useful corpus should collect fields that are plausibly known before the
# reaction window and that can be reviewed independently of the price move.
COMMON_CORPUS_COLUMNS = [
    "corpus_name",
    "event_family",
    "review_status",
    "label_quality",
    "source_doc_ids",
    "evidence_status",
]

DOMAIN_SPECS: dict[str, dict[str, object]] = {
    "earnings_guidance": {
        "description": "Earnings, segment, margin, and forward-guidance catalysts.",
        "event_type": "earnings",
        "default_subtype": "quarterly_results",
        "source_types": ["sec_8k", "press_release", "earnings_call", "investor_relations"],
        "domain_columns": [
            "fiscal_period_end",
            "fiscal_quarter",
            "fiscal_year",
            "primary_surprise_metric",
            "consensus_eps",
            "actual_eps",
            "eps_surprise_pct",
            "consensus_revenue",
            "actual_revenue",
            "revenue_surprise_pct",
            "consensus_gross_margin",
            "actual_gross_margin",
            "gross_margin_surprise_pct",
            "consensus_forward_revenue",
            "guidance_revenue_mid",
            "guidance_revenue_surprise_pct",
            "implied_move_pct",
            "analyst_count",
        ],
        "required_review_columns": ["event_time", "release_session", "source_type", "source_url"],
    },
    "fda_biotech": {
        "description": "FDA decisions, clinical trial readouts, and biotech/pharma catalysts.",
        "event_type": "regulatory",
        "default_subtype": "fda_or_trial_catalyst",
        "source_types": ["fda", "clinicaltrials", "company_press_release", "sec_8k"],
        "domain_columns": [
            "agency",
            "drug_or_device",
            "indication",
            "trial_phase",
            "trial_result",
            "primary_endpoint_met",
            "secondary_endpoint_signal",
            "safety_signal",
            "pdufa_decision",
            "approval_status",
            "market_size_estimate",
            "pipeline_concentration_pct",
            "cash_runway_months",
            "prior_probability",
        ],
        "required_review_columns": ["agency", "drug_or_device", "indication", "event_time", "source_url"],
    },
    "regulatory_legal": {
        "description": "Regulatory, litigation, antitrust, court, and enforcement events.",
        "event_type": "regulatory",
        "default_subtype": "regulatory_or_legal_action",
        "source_types": ["government", "court", "regulator", "company_filing", "press_release"],
        "domain_columns": [
            "agency",
            "jurisdiction",
            "action_type",
            "case_or_docket_id",
            "affected_business_line",
            "fine_or_penalty_amount",
            "remedy_risk",
            "injunction_risk",
            "novelty",
            "appeal_status",
            "expected_resolution_window",
        ],
        "required_review_columns": ["agency", "jurisdiction", "action_type", "event_time", "source_url"],
    },
    "cyber_incident": {
        "description": "Cybersecurity incidents, breaches, ransomware, outages, and disclosures.",
        "event_type": "cybersecurity",
        "default_subtype": "cyber_incident",
        "source_types": ["sec_8k", "company_disclosure", "regulator", "security_advisory", "news"],
        "domain_columns": [
            "incident_type",
            "breach_confirmed",
            "systems_affected",
            "customer_data_exposed",
            "ransomware",
            "operational_disruption",
            "disclosure_delay_days",
            "estimated_cost",
            "insurance_coverage_known",
            "regulatory_notification_required",
            "severity_score",
        ],
        "required_review_columns": ["incident_type", "event_time", "source_url"],
    },
    "recall_safety": {
        "description": "Product recalls, safety notices, NHTSA/CPSC/FDA device notices, and field actions.",
        "event_type": "recall",
        "default_subtype": "product_safety_recall",
        "source_types": ["nhtsa", "cpsc", "fda", "company_press_release", "regulator"],
        "domain_columns": [
            "agency",
            "product_or_model",
            "recall_class",
            "recall_units",
            "safety_risk",
            "injuries_or_deaths_reported",
            "remedy_available",
            "estimated_cost",
            "affected_revenue_pct",
            "production_halt",
            "geography",
        ],
        "required_review_columns": ["agency", "product_or_model", "recall_units", "event_time", "source_url"],
    },
    "capital_raise_dilution": {
        "description": "Equity offerings, ATM programs, convertibles, shelf registrations, liquidity warnings, and dilution events.",
        "event_type": "financing",
        "default_subtype": "capital_raise_or_dilution",
        "source_types": ["sec_filing", "prospectus", "company_press_release", "8-k", "s-1", "s-3", "424b5"],
        "domain_columns": [
            "financing_event_type",
            "security_type",
            "offering_amount",
            "gross_proceeds",
            "net_proceeds",
            "shares_offered",
            "price_per_share",
            "atm_capacity",
            "shelf_amount",
            "convertible_principal",
            "conversion_price",
            "warrant_coverage",
            "discount_to_last_close",
            "offering_size_to_market_cap",
            "cash_runway_months",
            "going_concern_warning",
            "liquidity_warning",
            "use_of_proceeds",
            "underwriter_or_agent",
            "primary_dilution_metric",
        ],
        "required_review_columns": ["financing_event_type", "security_type", "event_time", "source_type", "source_url"],
    },
}


@dataclass
class CorpusDiagnostics:
    rows_total: int = 0
    rows_ok: int = 0
    rows_warn: int = 0
    rows_fail: int = 0
    issues: dict[str, int] = field(default_factory=dict)

    def add(self, issue: str, *, fail: bool = False) -> None:
        if fail:
            self.rows_fail += 1
        else:
            self.rows_warn += 1
        self.issues[issue] = self.issues.get(issue, 0) + 1

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_domain(domain: str) -> str:
    key = str(domain).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "earnings": "earnings_guidance",
        "guidance": "earnings_guidance",
        "fda": "fda_biotech",
        "biotech": "fda_biotech",
        "regulatory": "regulatory_legal",
        "legal": "regulatory_legal",
        "cyber": "cyber_incident",
        "breach": "cyber_incident",
        "recall": "recall_safety",
        "safety": "recall_safety",
        "capital_raise": "capital_raise_dilution",
        "capital_raises": "capital_raise_dilution",
        "dilution": "capital_raise_dilution",
        "financing": "capital_raise_dilution",
        "offering": "capital_raise_dilution",
        "offerings": "capital_raise_dilution",
        "atm": "capital_raise_dilution",
        "liquidity": "capital_raise_dilution",
    }
    key = aliases.get(key, key)
    if key not in DOMAIN_SPECS:
        raise ValueError(f"Unknown corpus domain {domain!r}. Available: {', '.join(sorted(DOMAIN_SPECS))}")
    return key


def list_corpus_domains() -> pd.DataFrame:
    rows = []
    for name, spec in DOMAIN_SPECS.items():
        rows.append(
            {
                "domain": name,
                "event_type": spec["event_type"],
                "default_subtype": spec["default_subtype"],
                "n_domain_columns": len(spec["domain_columns"]),
                "description": spec["description"],
            }
        )
    return pd.DataFrame(rows).sort_values("domain").reset_index(drop=True)


def corpus_columns(domain: str) -> list[str]:
    key = normalize_domain(domain)
    spec = DOMAIN_SPECS[key]
    base = REQUIRED_EVENT_COLUMNS + list(OPTIONAL_EVENT_COLUMNS_WITH_DEFAULTS.keys())
    # event_family is added to load_events defaults in v0.7, but keep this robust
    # when called against older manually authored files.
    if "event_family" not in base:
        base.append("event_family")
    cols = base + COMMON_CORPUS_COLUMNS + list(spec["domain_columns"])
    out: list[str] = []
    seen: set[str] = set()
    for col in cols:
        if col not in seen:
            seen.add(col)
            out.append(col)
    return out


def make_domain_event_template(
    domain: str,
    out_path: str | Path,
    *,
    tickers: Iterable[str] | None = None,
    corpus_name: str | None = None,
    rows_per_ticker: int = 1,
) -> pd.DataFrame:
    key = normalize_domain(domain)
    spec = DOMAIN_SPECS[key]
    cols = corpus_columns(key)
    rows: list[dict[str, object]] = []
    ticker_list = [str(t).upper() for t in (tickers or [])]
    if not ticker_list:
        ticker_list = [""]
    for ticker in ticker_list:
        for i in range(max(1, int(rows_per_ticker))):
            event_id = f"{key}_{ticker or 'TICKER'}_{i+1:03d}"
            row = {col: "" for col in cols}
            row.update(
                {
                    "event_id": event_id,
                    "ticker": ticker,
                    "event_time": "",
                    "event_type": str(spec["event_type"]),
                    "event_subtype": str(spec["default_subtype"]),
                    "event_family": key,
                    "summary": "",
                    "source_type": "",
                    "source_url": "",
                    "release_session": "unknown",
                    "expectedness": "unknown",
                    "surprise_direction": "unknown",
                    "surprise_magnitude": "unknown",
                    "materiality": "0.5",
                    "sector_benchmark": "",
                    "notes": "",
                    "corpus_name": corpus_name or key,
                    "review_status": "unreviewed",
                    "label_quality": "unreviewed",
                    "source_doc_ids": "",
                    "evidence_status": "missing",
                }
            )
            rows.append(row)
    df = pd.DataFrame(rows, columns=cols)
    p = ensure_parent(out_path)
    df.to_csv(p, index=False)
    return df


def _string_nonempty(value: object) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    return text not in {"", "nan", "none", "null", "unknown"}


def validate_corpus_frame(df: pd.DataFrame, *, domain: str | None = None, min_materiality: float = 0.0) -> tuple[pd.DataFrame, CorpusDiagnostics]:
    out = df.copy()
    diag = CorpusDiagnostics(rows_total=len(out))
    if domain:
        domains = [normalize_domain(domain)]
    elif "event_family" in out.columns and out["event_family"].notna().any():
        domains = sorted({normalize_domain(v) for v in out["event_family"].dropna().astype(str) if _string_nonempty(v)})
    else:
        domains = []

    for col in ["review_status", "label_quality", "evidence_status", "corpus_name"]:
        if col not in out.columns:
            out[col] = ""

    statuses: list[str] = []
    issue_lists: list[str] = []
    for _, row in out.iterrows():
        issues: list[str] = []
        # Required generic event columns.
        for col in REQUIRED_EVENT_COLUMNS:
            if col not in out.columns or not _string_nonempty(row.get(col)):
                issues.append(f"missing_{col}")
        try:
            mat = float(row.get("materiality", np.nan))
            if np.isnan(mat) or mat < min_materiality:
                issues.append("low_or_missing_materiality")
        except Exception:
            issues.append("invalid_materiality")
        fam = str(row.get("event_family", domain or "")).strip().lower()
        try:
            fam = normalize_domain(fam) if _string_nonempty(fam) else (normalize_domain(domain) if domain else "")
        except Exception:
            issues.append("unknown_event_family")
            fam = ""
        if fam:
            spec = DOMAIN_SPECS[fam]
            for col in spec["required_review_columns"]:
                if col not in out.columns or not _string_nonempty(row.get(col)):
                    issues.append(f"missing_{fam}_{col}")
        else:
            if domains:
                issues.append("missing_event_family")
        review_status = str(row.get("review_status", "")).strip().lower()
        if review_status not in {"reviewed", "curated", "approved"}:
            issues.append("not_reviewed")
        label_quality = str(row.get("label_quality", "")).strip().lower()
        if label_quality not in {"high", "medium", "reviewed", "curated"}:
            issues.append("low_label_quality")
        evidence_status = str(row.get("evidence_status", "")).strip().lower()
        if evidence_status not in {"verified", "source_backed", "evidence_backed"} and not _string_nonempty(row.get("source_doc_ids")):
            issues.append("missing_evidence")

        if issues:
            status = "fail" if any(i.startswith("missing_event_id") or i.startswith("missing_ticker") or i.startswith("missing_event_time") for i in issues) else "warn"
            if status == "fail":
                diag.rows_fail += 1
            else:
                diag.rows_warn += 1
            for issue in issues:
                diag.issues[issue] = diag.issues.get(issue, 0) + 1
        else:
            status = "ok"
            diag.rows_ok += 1
        statuses.append(status)
        issue_lists.append(";".join(issues))
    out["corpus_validation_status"] = statuses
    out["corpus_validation_issues"] = issue_lists
    return out, diag


def validate_corpus_csv(
    events_path: str | Path,
    out_path: str | Path | None = None,
    *,
    domain: str | None = None,
    min_materiality: float = 0.0,
) -> tuple[pd.DataFrame, CorpusDiagnostics]:
    df = pd.read_csv(events_path)
    validated, diag = validate_corpus_frame(df, domain=domain, min_materiality=min_materiality)
    if out_path:
        p = ensure_parent(out_path)
        validated.to_csv(p, index=False)
    return validated, diag


def build_curated_corpus(
    inputs: Iterable[str | Path],
    out_path: str | Path,
    *,
    domain: str | None = None,
    corpus_name: str | None = None,
    require_reviewed: bool = False,
    min_materiality: float = 0.0,
) -> tuple[pd.DataFrame, CorpusDiagnostics]:
    frames = []
    for path in inputs:
        df = pd.read_csv(path)
        df["corpus_input_path"] = str(path)
        frames.append(df)
    if not frames:
        raise ValueError("At least one input CSV is required")
    merged = pd.concat(frames, ignore_index=True, sort=False)
    if domain:
        merged["event_family"] = normalize_domain(domain)
    elif "event_family" not in merged.columns:
        merged["event_family"] = "unknown"
    if corpus_name:
        merged["corpus_name"] = corpus_name
    elif "corpus_name" not in merged.columns:
        merged["corpus_name"] = merged["event_family"]

    # Fill event defaults and validate via the standard event loader.  This keeps
    # the narrow-domain corpus compatible with the rest of the pipeline.
    for col, default in OPTIONAL_EVENT_COLUMNS_WITH_DEFAULTS.items():
        if col not in merged.columns:
            merged[col] = default
    for col in REQUIRED_EVENT_COLUMNS:
        if col not in merged.columns:
            merged[col] = ""
    if "event_family" not in merged.columns:
        merged["event_family"] = normalize_domain(domain) if domain else "unknown"
    if merged["event_id"].duplicated().any():
        # Deterministically suffix duplicates rather than silently dropping rows.
        counts: dict[str, int] = {}
        new_ids = []
        for eid in merged["event_id"].astype(str):
            counts[eid] = counts.get(eid, 0) + 1
            new_ids.append(eid if counts[eid] == 1 else f"{eid}__dup{counts[eid]}")
        merged["event_id"] = new_ids

    validated, diag = validate_corpus_frame(merged, domain=domain, min_materiality=min_materiality)
    if require_reviewed:
        validated = validated[validated["corpus_validation_status"] == "ok"].copy()
    # Attempt full event-schema load on the output-compatible subset.  If a row
    # fails because event_time is blank, validation already exposes that as fail;
    # do not drop it unless require_reviewed was requested.
    if require_reviewed and not validated.empty:
        tmp = ensure_parent(Path(out_path).with_suffix(".tmp_events.csv"))
        validated.to_csv(tmp, index=False)
        loaded = load_events(tmp)
        tmp.unlink(missing_ok=True)
        # Preserve extra columns/load_events normalized core columns.
        validated = loaded
    p = ensure_parent(out_path)
    validated.to_csv(p, index=False)
    return validated, diag


def corpus_quality_summary(validated: pd.DataFrame) -> dict[str, object]:
    total = int(len(validated))
    status_counts = validated.get("corpus_validation_status", pd.Series(dtype=str)).value_counts(dropna=False).to_dict()
    family_counts = validated.get("event_family", pd.Series(dtype=str)).astype(str).value_counts(dropna=False).to_dict()
    label_counts = validated.get("label_quality", pd.Series(dtype=str)).astype(str).value_counts(dropna=False).to_dict()
    review_counts = validated.get("review_status", pd.Series(dtype=str)).astype(str).value_counts(dropna=False).to_dict()
    issue_counts: dict[str, int] = {}
    if "corpus_validation_issues" in validated.columns:
        for issues in validated["corpus_validation_issues"].fillna("").astype(str):
            for issue in [i for i in issues.split(";") if i]:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
    return {
        "rows_total": total,
        "status_counts": status_counts,
        "event_family_counts": family_counts,
        "label_quality_counts": label_counts,
        "review_status_counts": review_counts,
        "issue_counts": dict(sorted(issue_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
    }
