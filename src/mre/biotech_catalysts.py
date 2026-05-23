from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re

import numpy as np
import pandas as pd

from .events import make_event_template
from .ingestion import IngestionDiagnostics, build_sec_source_document_manifest
from .paths import ensure_parent
from .sec import SecClient
from .source_docs import SOURCE_DOC_COLUMNS, SourceDocument, load_source_documents, make_source_docs_template


BIOTECH_CATALYST_DOMAIN = "biotech_fda_clinical_catalyst"

BIOTECH_CATALYST_EVENT_TYPES = (
    "fda_approval",
    "fda_complete_response_letter",
    "fda_advisory_committee_positive",
    "fda_advisory_committee_negative",
    "phase_1_readout",
    "phase_2_readout",
    "phase_3_readout",
    "pivotal_trial_readout",
    "trial_halt",
    "trial_discontinuation",
    "safety_signal",
    "endpoint_failure",
    "endpoint_success",
    "label_expansion",
    "accelerated_approval",
    "priority_review",
    "breakthrough_designation",
    "fast_track_designation",
    "orphan_drug_designation",
)

DESIGNATION_ONLY_EVENT_TYPES = {
    "priority_review",
    "breakthrough_designation",
    "fast_track_designation",
    "orphan_drug_designation",
}
APPROVAL_OR_LABEL_EVENT_TYPES = {"fda_approval", "accelerated_approval", "label_expansion"}
REGULATORY_DECISION_EVENT_TYPES = APPROVAL_OR_LABEL_EVENT_TYPES | {
    "fda_complete_response_letter",
    "fda_advisory_committee_positive",
    "fda_advisory_committee_negative",
    "priority_review",
    "breakthrough_designation",
    "fast_track_designation",
    "orphan_drug_designation",
}
READOUT_EVENT_TYPES = {"phase_1_readout", "phase_2_readout", "phase_3_readout", "pivotal_trial_readout", "endpoint_success", "endpoint_failure"}
NEGATIVE_EVENT_TYPES = {
    "fda_complete_response_letter",
    "fda_advisory_committee_negative",
    "trial_halt",
    "trial_discontinuation",
    "safety_signal",
    "endpoint_failure",
}
BINARY_CATALYST_EVENT_TYPES = (
    APPROVAL_OR_LABEL_EVENT_TYPES
    | {
        "fda_complete_response_letter",
        "fda_advisory_committee_positive",
        "fda_advisory_committee_negative",
        "phase_2_readout",
        "phase_3_readout",
        "pivotal_trial_readout",
        "trial_halt",
        "trial_discontinuation",
        "safety_signal",
        "endpoint_failure",
        "endpoint_success",
    }
)

BIOTECH_FALSE_POSITIVE_TAXONOMY = {
    "enrollment_update_not_binary": "Enrollment or first-patient dosing without new efficacy/safety results.",
    "publication_or_conference_notice_not_topline": "Conference, poster, abstract, or publication notice without new topline facts.",
    "pipeline_update_not_binary": "Pipeline status, business update, or expected future readout without current results.",
    "trial_initiation_not_binary": "Trial start, IND clearance, or first dose without efficacy/safety results.",
    "trial_design_not_binary": "Trial design, protocol, or endpoint description without reported results.",
    "previously_announced_not_new": "Previously announced or previously disclosed results reused as background.",
    "background_approval_language_not_decision": "Label, pathway, post-approval, or potential approval language without a current decision.",
    "boilerplate_or_risk_factor_not_event": "About-company, risk-factor, or forward-looking text.",
    "pipeline_table_requires_new_result": "Pipeline table or business-highlight row needs explicit new result/regulatory decision language.",
}

NON_EVENT_SECTIONS = {"boilerplate", "risk_factor"}
BODY_ONLY_SECTIONS = {"body", "pipeline_table"}

BIOTECH_SEC_FORMS = ("8-K",)
BIOTECH_CATALYST_8K_ITEMS = "7.01,8.01"
BIOTECH_CATALYST_EXHIBIT_PATTERN = (
    r"(?i)(ex[-_]?99|exhibit[-_ ]?99|dex99|99[._-]?1|press[-_ ]?release|clinical|trial|phase|"
    r"fda|approval|complete[-_ ]?response|crl|pdufa|endpoint|topline|readout|adcom|advisory|"
    r"label|safety|designation|breakthrough|fast[-_ ]?track|orphan)"
)

BIOTECH_FACT_COLUMNS = [
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

BIOTECH_FEATURE_COLUMNS = [
    "event_id",
    "ticker",
    "event_time",
    "source_doc_ids",
    "usable_fact_count",
    "source_type",
    "source_url",
    "source_evidence_text",
    "biotech_catalyst_event_type",
    "event_type",
    "drug_asset",
    "indication",
    "trial_phase",
    "nct_id",
    "trial_name",
    "primary_endpoint",
    "endpoint_met",
    "p_value",
    "hazard_ratio",
    "response_rate",
    "overall_survival",
    "progression_free_survival",
    "safety_issue",
    "adverse_event_language",
    "fda_action",
    "approval_status",
    "complete_response_letter_flag",
    "advisory_committee_vote_for",
    "advisory_committee_vote_against",
    "pdufa_date",
    "accelerated_approval_flag",
    "label_expansion_flag",
    "affected_pipeline_asset_count",
    "company_pipeline_concentration_notes",
    "binary_catalyst_flag",
    "clinical_trial_readout_flag",
    "regulatory_decision_flag",
    "designation_only_flag",
    "safety_negative_flag",
    "approval_or_label_expansion_flag",
    "trial_failure_flag",
    "trial_success_flag",
    "pipeline_concentration_required_flag",
    "event_direction_pre_price",
    "materiality_pre_price",
    "label_quality",
    "evidence_status",
    "parser_quality_flags",
]


@dataclass(frozen=True)
class BiotechCatalystFact:
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


@dataclass(frozen=True)
class _SectionedSegment:
    text: str
    lower: str
    section: str
    index: int


def _norm_space(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _segments(text: str) -> list[str]:
    parts = []
    for raw in re.split(r"(?<!\d)[\.;!?](?!\d)|\n+", str(text or "")):
        seg = _norm_space(raw)
        if 12 <= len(seg) <= 900:
            parts.append(seg)
    return parts


def _contains_any(text: str, terms: list[str] | tuple[str, ...] | set[str]) -> bool:
    low = text.lower()
    return any(term.lower() in low for term in terms)


def _sectioned_segments(text: str) -> list[_SectionedSegment]:
    segments: list[_SectionedSegment] = []
    section = "body"
    nonblank_line_index = -1
    for raw in str(text or "").splitlines():
        line = _norm_space(raw)
        if not line:
            continue
        nonblank_line_index += 1
        low = line.lower()
        stripped = low.strip(" :-")
        if re.match(r"^(about|about the company|about [a-z0-9 .,&'-]+)$", stripped):
            section = "boilerplate"
            continue
        if _contains_any(low, ["forward-looking statements", "cautionary note", "safe harbor", "risk factors"]):
            section = "risk_factor"
        elif re.match(r"^(summary of business highlights|pipeline|recent business highlights)$", stripped):
            section = "pipeline_table"

        line_section = section
        if nonblank_line_index <= 1 and section == "body":
            line_section = "headline"
        elif nonblank_line_index <= 5 and section == "body":
            line_section = "lead_paragraph"
        if line.startswith(("\u2022", "-", "\u25e6", "*")) or re.match(r"^[A-Za-z].{0,90}:\s", line):
            if section not in NON_EVENT_SECTIONS:
                line_section = "pipeline_table"

        parts = _segments(line)
        if not parts and 12 <= len(line) <= 900:
            parts = [line]
        for part in parts:
            part_low = part.lower()
            part_section = line_section
            if _contains_any(part_low, ["forward-looking", "actual results", "risks and uncertainties", "may differ materially"]):
                part_section = "risk_factor"
            if _contains_any(part_low, ["is headquartered", "for more information", "please visit"]) and section == "boilerplate":
                part_section = "boilerplate"
            segments.append(_SectionedSegment(part, part_low, part_section, len(segments)))
    return segments


def _section_priority(section: str) -> int:
    return {
        "headline": 0,
        "lead_paragraph": 1,
        "body": 2,
        "pipeline_table": 3,
        "boilerplate": 8,
        "risk_factor": 9,
    }.get(section, 5)


def _ranked_segments(text: str) -> list[_SectionedSegment]:
    return sorted(_sectioned_segments(text), key=lambda seg: (_section_priority(seg.section), seg.index))


def _false_positive_reason(seg: _SectionedSegment) -> str:
    low = seg.lower
    has_result_fact = bool(
        _endpoint_met_signal(low) is not None
        or _contains_any(low, ["topline results", "top-line results", "statistically significant", "serious adverse event", "safety signal"])
    )
    if seg.section in NON_EVENT_SECTIONS or _contains_any(low, ["actual results could differ", "results to differ materially", "risks and uncertainties"]):
        return "boilerplate_or_risk_factor_not_event"
    if _contains_any(low, ["previously announced", "as previously announced", "previously disclosed", "as previously disclosed"]) or re.search(
        r"\bin\s+(?:january|february|march|april|may|june|july|august|september|october|november|december|q[1-4]),?\s+we\s+announced\b",
        low,
    ):
        return "previously_announced_not_new"
    if re.search(r"\b(will|plans? to|expects? to|scheduled to|accepted to|accepted for)\s+(present|report|announce|share|publish)\b", low):
        if not has_result_fact:
            return "publication_or_conference_notice_not_topline"
    if _contains_any(low, ["poster presentation", "oral presentation", "accepted for presentation", "abstract", "published in", "publication in"]):
        if not has_result_fact:
            return "publication_or_conference_notice_not_topline"
    if _contains_any(low, ["completed enrollment", "enrollment completed", "enrollment is complete", "enrolled first patient"]):
        return "enrollment_update_not_binary"
    if _contains_any(low, ["first patient dosed", "dosed first patient", "initiated dosing", "initiated a phase", "initiated the phase", "trial initiation"]):
        return "trial_initiation_not_binary"
    if _contains_any(low, ["trial design", "study design", "protocol amendment", "designed to evaluate", "designed to assess"]):
        if not has_result_fact:
            return "trial_design_not_binary"
    if _contains_any(low, ["currently being evaluated", "is ongoing", "ongoing phase", "expects to share", "expected to share", "expected by", "readout by"]):
        if not has_result_fact:
            return "pipeline_update_not_binary"
    if re.search(r"\b(top-?line|readout|data|results)\b.{0,40}\bexpected\b|\bexpected\b.{0,40}\b(top-?line|readout|data|results)\b", low) and not has_result_fact:
        return "pipeline_update_not_binary"
    if _contains_any(
        low,
        [
            "approved under accelerated approval",
            "indication is approved",
            "continued approval",
            "post-approval",
            "support accelerated approval",
            "potential priority review",
            "potential accelerated approval",
            "may be contingent",
            "has not yet been established",
        ],
    ):
        return "background_approval_language_not_decision"
    if seg.section == "pipeline_table":
        return "pipeline_table_requires_new_result"
    return ""


def _collect_false_positive_flags(segments: list[_SectionedSegment]) -> list[str]:
    flags: list[str] = []
    for seg in segments:
        low = seg.lower
        has_result_fact = bool(
            _endpoint_met_signal(low) is not None
            or _contains_any(low, ["topline results", "top-line results", "statistically significant", "serious adverse event", "safety signal"])
        )
        if _contains_any(low, ["completed enrollment", "enrollment completed", "enrollment is complete", "enrolled first patient"]):
            flags.append("enrollment_update_not_binary")
        if _contains_any(low, ["first patient dosed", "dosed first patient", "initiated dosing", "initiated a phase", "initiated the phase", "trial initiation"]):
            flags.append("trial_initiation_not_binary")
        if _contains_any(low, ["trial design", "study design", "protocol amendment", "designed to evaluate", "designed to assess"]) and not has_result_fact:
            flags.append("trial_design_not_binary")
        if (
            re.search(r"\b(will|plans? to|expects? to|scheduled to|accepted to|accepted for)\s+(present|report|announce|share|publish)\b", low)
            or _contains_any(low, ["poster presentation", "oral presentation", "accepted for presentation", "abstract", "published in", "publication in"])
        ) and not has_result_fact:
            flags.append("publication_or_conference_notice_not_topline")
        reason = _false_positive_reason(seg)
        if reason and reason not in flags:
            flags.append(reason)
    return list(dict.fromkeys(flags))


def _first_matching_segment(text: str, patterns: list[str]) -> str:
    for seg in _segments(text):
        for pattern in patterns:
            if re.search(pattern, seg, flags=re.I):
                return seg
    return ""


def _first_matching_sectioned_segment(segments: list[_SectionedSegment], patterns: list[str]) -> _SectionedSegment | None:
    for seg in sorted(segments, key=lambda item: (_section_priority(item.section), item.index)):
        for pattern in patterns:
            if re.search(pattern, seg.text, flags=re.I):
                return seg
    return None


def _fact(
    doc: SourceDocument,
    name: str,
    value: str | float | bool,
    unit: str,
    evidence: str,
    confidence: float,
    method: str,
    flags: list[str] | tuple[str, ...] | set[str] | str = "",
) -> BiotechCatalystFact:
    if isinstance(flags, str):
        flag_text = flags
    else:
        flag_text = ";".join(sorted({str(f) for f in flags if str(f).strip()}))
    return BiotechCatalystFact(
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


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _bool_or_na(value: object) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _to_float(value: object) -> float:
    return float(pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0])


def infer_trial_phase(text: str) -> tuple[str, str, float]:
    for seg in _segments(text[:8000]):
        low = seg.lower()
        if re.search(r"\bphase\s*(?:iii|3)\b", low):
            return "phase_3", seg, 0.92
        if re.search(r"\bphase\s*(?:ii/iii|2/3|iib|2b)\b", low):
            return "phase_2_3", seg, 0.90
        if re.search(r"\bphase\s*(?:ii|2)\b", low):
            return "phase_2", seg, 0.90
        if re.search(r"\bphase\s*(?:i/ii|1/2|ib|1b)\b", low):
            return "phase_1_2", seg, 0.86
        if re.search(r"\bphase\s*(?:i|1)\b", low):
            return "phase_1", seg, 0.86
        if re.search(r"\bpivotal\b", low):
            return "pivotal", seg, 0.78
    return "", "", 0.0


def _has_new_result_signal(low: str) -> bool:
    has_result_fact = bool(
        _endpoint_met_signal(low) is not None
        or _contains_any(low, ["topline results", "top-line results", "statistically significant", "safety signal", "serious adverse event"])
    )
    if re.search(r"\b(will|plans? to|expects? to|scheduled to)\s+(present|report|announce|share|publish)\b", low) and not has_result_fact:
        return False
    if _contains_any(low, ["previously announced", "as previously disclosed", "actual results", "forward-looking statements"]) or re.search(
        r"\bin\s+(?:january|february|march|april|may|june|july|august|september|october|november|december|q[1-4]),?\s+we\s+announced\b",
        low,
    ):
        return False
    if re.search(r"\b(top-?line|readout|data|results)\b.{0,40}\bexpected\b|\bexpected\b.{0,40}\b(top-?line|readout|data|results)\b", low) and not has_result_fact:
        return False
    if _contains_any(low, ["completed enrollment", "enrolled", "randomized"]) and not _contains_any(
        low,
        ["topline", "results", "readout", "met the primary endpoint", "met its primary endpoint", "failed to meet", "statistically significant", "showed", "demonstrated"],
    ):
        return False
    explicit_result = _contains_any(
        low,
        [
            "announced topline results",
            "announced top-line results",
            "reported topline results",
            "reported top-line results",
            "topline results",
            "top-line results",
            "readout",
            "reported results",
            "announced results",
            "met the primary endpoint",
            "met its primary endpoint",
            "met the study's primary endpoint",
            "met the trial's primary endpoint",
            "failed to meet",
            "did not meet",
            "missed the primary endpoint",
            "statistically significant",
            "demonstrated a statistically significant",
            "showed a statistically significant",
            "positive results",
            "negative results",
        ],
    )
    if not explicit_result:
        return False
    return _contains_any(low, ["trial", "study", "phase", "endpoint", "topline", "data", "clinical"])


def _endpoint_met_signal(low: str) -> bool | None:
    if re.search(r"\b(did not|failed to|fails? to|missed|not achieve|was not met|were not met)\b.{0,80}\bprimary endpoint", low):
        return False
    if re.search(r"\bprimary endpoint\b.{0,80}\b(was not met|were not met|not achieved|failed|missed)", low):
        return False
    if re.search(r"\b(met|achieved|satisfied)\b.{0,80}\bprimary endpoint", low):
        return True
    if re.search(r"\bprimary endpoint\b.{0,80}\b(was met|were met|achieved|satisfied)", low):
        return True
    return None


def _is_negated_safety_language(text: str) -> bool:
    return bool(
        re.search(
            r"\b(no|without)\s+(?:new\s+)?(?:major\s+|meaningful\s+)?safety\s+(?:signals?|concerns?|issues?)\b|\bgenerally well tolerated\b",
            text,
            flags=re.I,
        )
    )


def _adcom_votes(text: str) -> tuple[int | None, int | None, str]:
    for seg in _segments(text[:8000]):
        if not re.search(r"\b(advisory committee|adcom|committee)\b", seg, flags=re.I) or not re.search(r"\b(vote|voted|votes)\b", seg, flags=re.I):
            continue
        yes_no = re.search(r"(?P<yes>\d{1,2})\s*(?:yes|for|in favor).{0,80}?(?P<no>\d{1,2})\s*(?:no|against)", seg, flags=re.I)
        if yes_no:
            return int(yes_no.group("yes")), int(yes_no.group("no")), seg
        vote = re.search(r"(?P<for>\d{1,2})\s*(?:-|to)\s*(?P<against>\d{1,2})", seg)
        if vote:
            return int(vote.group("for")), int(vote.group("against")), seg
    return None, None, ""


def _current_action_language(low: str) -> bool:
    return bool(
        re.search(
            r"\b(today announced|announced|reported|received|granted|issued|approved|approves|accepted|voted|placed|halted|discontinued)\b",
            low,
        )
    )


def _regulatory_segment_is_current(seg: _SectionedSegment, *, require_fda: bool = True) -> bool:
    low = seg.lower
    reason = _false_positive_reason(seg)
    if reason and reason != "pipeline_table_requires_new_result":
        return False
    if require_fda and "fda" not in low and "u.s. food and drug administration" not in low:
        return False
    return _current_action_language(low)


def _readout_segment_is_current(seg: _SectionedSegment) -> bool:
    reason = _false_positive_reason(seg)
    if reason and reason != "pipeline_table_requires_new_result":
        return False
    if seg.section == "pipeline_table" and not _contains_any(
        seg.lower,
        [
            "topline",
            "top-line",
            "met its primary endpoint",
            "met the primary endpoint",
            "did not meet",
            "failed to meet",
            "statistically significant",
        ],
    ):
        return False
    return _has_new_result_signal(seg.lower)


def _phase_from_segment_or_document(seg: _SectionedSegment, doc_text: str) -> tuple[str, str, float]:
    phase, evidence, confidence = infer_trial_phase(seg.text)
    if phase:
        return phase, evidence or seg.text, max(confidence, 0.80)
    phase, evidence, confidence = infer_trial_phase(doc_text[:8000])
    return phase, evidence, confidence


def infer_biotech_catalyst_event_type(text: str) -> tuple[str, str, float, list[str]]:
    doc_text = _norm_space(text)
    low = doc_text.lower()
    segments = _sectioned_segments(text)
    ranked = sorted(segments, key=lambda seg: (_section_priority(seg.section), seg.index))
    flags: list[str] = _collect_false_positive_flags(segments)

    for seg in ranked:
        if ("complete response letter" in seg.lower or re.search(r"\bcrl\b", seg.lower)) and _regulatory_segment_is_current(seg, require_fda=False):
            return "fda_complete_response_letter", seg.text, 0.96, flags

    for seg in ranked:
        if "clinical hold" in seg.lower and _regulatory_segment_is_current(seg, require_fda=False):
            flags.append("safety_review_required")
            return "trial_halt", seg.text, 0.92, flags

    for seg in ranked:
        if _false_positive_reason(seg) and _false_positive_reason(seg) != "pipeline_table_requires_new_result":
            continue
        if re.search(r"\b(trial|study)\b.{0,80}\b(halted|paused|stopped|suspended)\b", seg.lower) or re.search(
            r"\b(halted|paused|stopped|suspended)\b.{0,80}\b(trial|study)\b", seg.lower
        ):
            return "trial_halt", seg.text, 0.90, flags

    for seg in ranked:
        if _false_positive_reason(seg) and _false_positive_reason(seg) != "pipeline_table_requires_new_result":
            continue
        if re.search(r"\b(discontinue|discontinued|terminate|terminated|stop development|will not continue)\b.{0,120}\b(trial|study|program|development)\b", seg.lower):
            return "trial_discontinuation", seg.text, 0.88, flags

    for seg in ranked:
        if _contains_any(seg.lower, ["label expansion", "expanded label", "expanded approval", "supplemental new drug application"]) and _contains_any(
            seg.lower, ["approved", "approval"]
        ) and _regulatory_segment_is_current(seg, require_fda=False):
            return "label_expansion", seg.text, 0.92, flags

    for seg in ranked:
        if "accelerated approval" in seg.lower and _contains_any(seg.lower, ["approved", "approval", "granted"]) and _regulatory_segment_is_current(seg):
            return "accelerated_approval", seg.text, 0.93, flags

    for seg in ranked:
        if (
            re.search(r"\bfda\b.{0,120}\b(approved|approves|approval)\b", seg.lower)
            or re.search(r"\b(approved|approval)\b.{0,120}\bfda\b", seg.lower)
        ) and _regulatory_segment_is_current(seg):
            return "fda_approval", seg.text, 0.94, flags

    vote_for, vote_against, vote_evidence = _adcom_votes(doc_text)
    if vote_for is not None and vote_against is not None:
        vote_segment = _first_matching_sectioned_segment(segments, [r"advisory committee|adcom|committee"])
        if vote_segment is None or _regulatory_segment_is_current(vote_segment, require_fda=False):
            event_type = "fda_advisory_committee_positive" if vote_for > vote_against else "fda_advisory_committee_negative"
            return event_type, vote_evidence, 0.90, flags
    for seg in ranked:
        if not re.search(r"\b(advisory committee|adcom)\b", seg.lower) or not _regulatory_segment_is_current(seg, require_fda=False):
            continue
        if _contains_any(seg.lower, ["recommended approval", "voted in favor", "positive vote"]):
            return "fda_advisory_committee_positive", seg.text, 0.84, flags
        if _contains_any(seg.lower, ["recommended against", "voted against", "negative vote"]):
            return "fda_advisory_committee_negative", seg.text, 0.84, flags

    for seg in ranked:
        if not _readout_segment_is_current(seg):
            continue
        endpoint_met = _endpoint_met_signal(seg.lower)
        trial_phase, phase_evidence, phase_conf = _phase_from_segment_or_document(seg, doc_text)
        if endpoint_met is False:
            if trial_phase in {"phase_3", "phase_2_3"}:
                return "phase_3_readout", seg.text, max(phase_conf, 0.88), flags
            if trial_phase.startswith("phase_2"):
                return "phase_2_readout", seg.text, max(phase_conf, 0.86), flags
            return "endpoint_failure", seg.text, 0.92, flags
        if endpoint_met is True:
            if "pivotal" in seg.lower or trial_phase == "pivotal":
                return "pivotal_trial_readout", seg.text, max(phase_conf, 0.86), flags
            if trial_phase in {"phase_3", "phase_2_3"}:
                return "phase_3_readout", seg.text, max(phase_conf, 0.88), flags
            if trial_phase.startswith("phase_2"):
                return "phase_2_readout", seg.text, max(phase_conf, 0.86), flags
            if trial_phase.startswith("phase_1"):
                return "phase_1_readout", seg.text, max(phase_conf, 0.80), flags
            return "endpoint_success", seg.text, 0.84, flags
        flags.append("endpoint_direction_unclear")
        if "pivotal" in seg.lower or trial_phase == "pivotal":
            return "pivotal_trial_readout", seg.text or phase_evidence, max(phase_conf, 0.82), flags
        if trial_phase in {"phase_3", "phase_2_3"}:
            return "phase_3_readout", seg.text or phase_evidence, max(phase_conf, 0.82), flags
        if trial_phase.startswith("phase_2"):
            return "phase_2_readout", seg.text or phase_evidence, max(phase_conf, 0.80), flags
        if trial_phase.startswith("phase_1"):
            return "phase_1_readout", seg.text or phase_evidence, max(phase_conf, 0.76), flags

    safety_terms = [
        "safety signal",
        "serious adverse event",
        "serious adverse events",
        "patient death",
        "patient deaths",
        "liver toxicity",
        "cardiac toxicity",
        "dose-limiting toxicity",
        "boxed warning",
    ]
    for seg in ranked:
        if _false_positive_reason(seg) and _false_positive_reason(seg) != "pipeline_table_requires_new_result":
            continue
        if _contains_any(seg.lower, safety_terms):
            evidence = seg.text
            if not _is_negated_safety_language(evidence):
                flags.append("safety_issue_present")
                return "safety_signal", evidence, 0.86, flags

    for seg in ranked:
        reason = _false_positive_reason(seg)
        if reason and reason != "pipeline_table_requires_new_result":
            continue
        current_designation = bool("granted" in seg.lower or "today announced" in seg.lower or "announces" in seg.lower or "announced" in seg.lower)
        if "breakthrough therapy designation" in seg.lower or "breakthrough designation" in seg.lower:
            if current_designation and not _contains_any(seg.lower, ["in addition to", "also has", "has received", "originally granted", "maintain"]):
                flags.append("designation_only_weaker_signal")
                return "breakthrough_designation", seg.text, 0.90, flags
        if "fast track designation" in seg.lower or "fast-track designation" in seg.lower:
            if current_designation and not _contains_any(seg.lower, ["in addition to", "also has", "has received", "originally granted", "maintain"]):
                flags.append("designation_only_weaker_signal")
                return "fast_track_designation", seg.text, 0.90, flags
        if "orphan drug designation" in seg.lower:
            if current_designation and not _contains_any(seg.lower, ["in addition to", "also has", "has received", "originally granted", "maintain"]):
                flags.append("designation_only_weaker_signal")
                return "orphan_drug_designation", seg.text, 0.88, flags
        if "priority review" in seg.lower:
            if current_designation and not _contains_any(seg.lower, ["potential priority review", "eligible for priority review"]):
                flags.append("designation_only_weaker_signal")
                return "priority_review", seg.text, 0.86, flags

    endpoint_met = _endpoint_met_signal(low)
    if endpoint_met is True:
        endpoint_segment = _first_matching_sectioned_segment(segments, [r"met.*primary endpoint|primary endpoint.*met"])
        if endpoint_segment and _readout_segment_is_current(endpoint_segment):
            return "endpoint_success", endpoint_segment.text, 0.84, flags
    if endpoint_met is False:
        endpoint_segment = _first_matching_sectioned_segment(segments, [r"did not meet|failed to meet|missed.*primary endpoint|primary endpoint.*not met"])
        if endpoint_segment and _readout_segment_is_current(endpoint_segment):
            return "endpoint_failure", endpoint_segment.text, 0.92, flags

    evidence_segment = _first_matching_sectioned_segment(segments, [r"FDA|trial|clinical|endpoint|approval|designation"])
    evidence = evidence_segment.text if evidence_segment else ""
    if evidence_segment and _false_positive_reason(evidence_segment):
        reason = _false_positive_reason(evidence_segment)
        if reason not in flags:
            flags.append(reason)
    return "unknown", evidence, 0.30, flags


ASSET_STOPWORDS = {
    "FDA",
    "NDA",
    "BLA",
    "CRL",
    "PDUFA",
    "Phase",
    "Complete",
    "Response",
    "Letter",
    "Company",
    "Trial",
    "Study",
    "Advisory",
    "Committee",
}


def extract_drug_asset(text: str) -> tuple[str, str, float]:
    patterns = [
        r"(?:for|of|with|to)\s+(?:its\s+)?(?:lead\s+)?(?:investigational\s+)?(?:product candidate\s+|drug candidate\s+|candidate\s+|therapy\s+|treatment\s+)?(?P<asset>[A-Z][A-Za-z0-9-]{2,}(?:\s?\([A-Za-z0-9-]+\))?)",
        r"(?P<asset>[A-Z][A-Za-z0-9-]{2,})\s+(?:was|has been|is)\s+(?:approved|granted|placed|accepted)",
        r"\b(?P<asset>[A-Z]{2,}[A-Za-z0-9-]*-\d+[A-Za-z0-9-]*|[A-Z][A-Za-z]+-\d+[A-Za-z0-9-]*|[A-Z]{2,}\d{2,}[A-Za-z0-9-]*)\b",
    ]
    for seg in _segments(text[:8000]):
        if not re.search(r"\b(FDA|trial|clinical|Phase|endpoint|approval|approved|designation|therapy|candidate|drug|treatment)\b", seg, flags=re.I):
            continue
        for pattern in patterns:
            match = re.search(pattern, seg)
            if not match:
                continue
            asset = _norm_space(match.group("asset")).strip(" ,")
            if not asset or asset.split()[0] in ASSET_STOPWORDS:
                continue
            if asset.lower() in {"the", "its", "for", "patients", "treatment"}:
                continue
            return asset, seg, 0.76 if "-" not in asset else 0.86
    return "", "", 0.0


def extract_indication(text: str) -> tuple[str, str, float]:
    patterns = [
        r"for the treatment of (?P<indication>[^.;,\n]+)",
        r"for treatment of (?P<indication>[^.;,\n]+)",
        r"in patients with (?P<indication>[^.;,\n]+)",
        r"in (?P<indication>[^.;,\n]+(?:cancer|carcinoma|disease|syndrome|disorder|tumors?|tumours?))",
    ]
    for seg in _segments(text[:8000]):
        for pattern in patterns:
            match = re.search(pattern, seg, flags=re.I)
            if not match:
                continue
            indication = _norm_space(match.group("indication")).strip(" ,")
            indication = re.sub(r"\s+(?:and|with)\s+(?:announced|reported|met|failed).*$", "", indication, flags=re.I)
            if 3 <= len(indication) <= 140:
                return indication, seg, 0.78
    return "", "", 0.0


def extract_nct_id(text: str) -> tuple[str, str, float]:
    match = re.search(r"\bNCT\d{8}\b", text, flags=re.I)
    if not match:
        return "", "", 0.0
    seg = _first_matching_segment(text, [re.escape(match.group(0))]) or match.group(0)
    return match.group(0).upper(), seg, 0.95


def extract_trial_name(text: str) -> tuple[str, str, float]:
    patterns = [
        r"\b(?P<name>[A-Z][A-Za-z0-9-]{2,})\s+(?:Phase\s+(?:1|2|3|I|II|III)\s+)?trial\b",
        r"\btrial\s+(?:called|known as)?\s*(?P<name>[A-Z][A-Za-z0-9-]{2,})\b",
        r"\((?P<name>[A-Z][A-Za-z0-9-]{2,})\)\s+trial\b",
    ]
    for seg in _segments(text[:8000]):
        for pattern in patterns:
            match = re.search(pattern, seg)
            if match:
                name = match.group("name")
                if name not in ASSET_STOPWORDS:
                    return name, seg, 0.70
    return "", "", 0.0


def extract_primary_endpoint(text: str) -> tuple[str, str, float]:
    for seg in _segments(text[:8000]):
        if "primary endpoint" not in seg.lower():
            continue
        match = re.search(r"primary endpoint(?:s)?(?:\s+of|\s+was|\s+were|\s*:)?\s+(?P<endpoint>[^.;]+)", seg, flags=re.I)
        if match:
            endpoint = _norm_space(match.group("endpoint")).strip(" ,")
            endpoint = re.sub(r"\b(was|were)\s+(met|not met|achieved).*$", "", endpoint, flags=re.I).strip(" ,")
            if endpoint:
                return endpoint[:220], seg, 0.76
        return seg[:220], seg, 0.66
    return "", "", 0.0


def extract_endpoint_met(text: str) -> tuple[bool | None, str, float]:
    for seg in _segments(text[:8000]):
        result = _endpoint_met_signal(seg.lower())
        if result is not None:
            return result, seg, 0.92
    return None, "", 0.0


def extract_statistical_facts(text: str) -> list[tuple[str, str | float, str, str, float, str]]:
    facts: list[tuple[str, str | float, str, str, float, str]] = []
    for seg in _segments(text[:12000]):
        p_match = re.search(r"\bp\s*(?:=|<|<=)\s*(?P<value>0?\.\d+)", seg, flags=re.I)
        if p_match:
            facts.append(("p_value", float(p_match.group("value")), "number", seg, 0.88, "p_value_regex"))
        hr_match = re.search(r"(?:hazard ratio|HR)\s*(?:=|of|was|:)?\s*(?P<value>0?\.\d+)", seg, flags=re.I)
        if hr_match:
            facts.append(("hazard_ratio", float(hr_match.group("value")), "ratio", seg, 0.86, "hazard_ratio_regex"))
        rr_match = re.search(r"(?:objective response rate|overall response rate|response rate|ORR)\s*(?:was|of|=|:)?\s*(?P<value>\d+(?:\.\d+)?)\s*%", seg, flags=re.I)
        if rr_match:
            facts.append(("response_rate", float(rr_match.group("value")) / 100.0, "proportion", seg, 0.84, "response_rate_regex"))
        os_match = re.search(r"(?:overall survival|OS)\s*(?:was|of|=|:)?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>months?|weeks?)", seg, flags=re.I)
        if os_match:
            facts.append(("overall_survival", f"{os_match.group('value')} {os_match.group('unit')}", "text", seg, 0.76, "overall_survival_regex"))
        pfs_match = re.search(r"(?:progression[- ]free survival|PFS)\s*(?:was|of|=|:)?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>months?|weeks?)", seg, flags=re.I)
        if pfs_match:
            facts.append(("progression_free_survival", f"{pfs_match.group('value')} {pfs_match.group('unit')}", "text", seg, 0.76, "progression_free_survival_regex"))
    return facts


def extract_pdufa_date(text: str) -> tuple[str, str, float]:
    month = r"January|February|March|April|May|June|July|August|September|October|November|December|Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sep\.?|Sept\.?|Oct\.?|Nov\.?|Dec\.?"
    patterns = [
        rf"PDUFA(?:\s+(?:target|action|goal))?\s+(?:date\s+)?(?:of|is|for|:)?\s*(?P<date>(?:{month})\s+\d{{1,2}},\s+\d{{4}})",
        r"PDUFA(?:\s+(?:target|action|goal))?\s+(?:date\s+)?(?:of|is|for|:)?\s*(?P<date>\d{4}-\d{2}-\d{2})",
    ]
    for seg in _segments(text[:8000]):
        if "pdufa" not in seg.lower():
            continue
        for pattern in patterns:
            match = re.search(pattern, seg, flags=re.I)
            if match:
                return _norm_space(match.group("date")), seg, 0.88
    return "", "", 0.0


def extract_safety_language(text: str) -> tuple[bool, str, float]:
    evidence = _first_matching_segment(
        text,
        [r"safety signal", r"serious adverse", r"patient death", r"toxicity", r"dose-limiting", r"clinical hold", r"boxed warning"],
    )
    if evidence and not _is_negated_safety_language(evidence):
        return True, evidence, 0.82
    return False, "", 0.0


def extract_pipeline_concentration(text: str) -> tuple[float, str, float]:
    evidence = _first_matching_segment(text, [r"only product candidate|sole clinical asset|single asset|lead product candidate|substantially all"])
    if not evidence:
        return np.nan, "", 0.0
    if re.search(r"\b(only|sole|single)\b", evidence, flags=re.I):
        return 1.0, evidence, 0.76
    return np.nan, evidence, 0.62


def _dedupe_facts(facts: list[BiotechCatalystFact]) -> list[BiotechCatalystFact]:
    best: dict[str, BiotechCatalystFact] = {}
    for fact in facts:
        current = best.get(fact.fact_name)
        if current is None or fact.confidence > current.confidence:
            best[fact.fact_name] = fact
    return sorted(best.values(), key=lambda f: f.fact_name)


def parse_biotech_catalyst_document(doc: SourceDocument) -> list[BiotechCatalystFact]:
    facts: list[BiotechCatalystFact] = []
    raw_doc_text = str(doc.text or "")
    doc_text = _norm_space(raw_doc_text)
    event_type, event_evidence, event_confidence, quality_flags = infer_biotech_catalyst_event_type(raw_doc_text)
    facts.append(_fact(doc, "event_type", event_type, "category", event_evidence, event_confidence, "document_keyword", quality_flags))
    if event_evidence:
        facts.append(_fact(doc, "source_evidence_text", event_evidence, "text", event_evidence, event_confidence, "event_evidence", quality_flags))

    trial_phase, phase_evidence, phase_confidence = infer_trial_phase(doc_text)
    if trial_phase:
        facts.append(_fact(doc, "trial_phase", trial_phase, "category", phase_evidence, phase_confidence, "trial_phase_regex"))

    asset, asset_evidence, asset_confidence = extract_drug_asset(doc_text)
    if asset:
        facts.append(_fact(doc, "drug_asset", asset, "text", asset_evidence, asset_confidence, "asset_regex"))
    indication, indication_evidence, indication_confidence = extract_indication(doc_text)
    if indication:
        facts.append(_fact(doc, "indication", indication, "text", indication_evidence, indication_confidence, "indication_regex"))
    nct_id, nct_evidence, nct_confidence = extract_nct_id(doc_text)
    if nct_id:
        facts.append(_fact(doc, "nct_id", nct_id, "identifier", nct_evidence, nct_confidence, "nct_regex"))
    trial_name, trial_evidence, trial_confidence = extract_trial_name(doc_text)
    if trial_name:
        facts.append(_fact(doc, "trial_name", trial_name, "text", trial_evidence, trial_confidence, "trial_name_regex"))
    endpoint, endpoint_evidence, endpoint_confidence = extract_primary_endpoint(doc_text)
    if endpoint:
        facts.append(_fact(doc, "primary_endpoint", endpoint, "text", endpoint_evidence, endpoint_confidence, "primary_endpoint_sentence"))
    endpoint_met, endpoint_met_evidence, endpoint_met_confidence = extract_endpoint_met(doc_text)
    if endpoint_met is not None:
        facts.append(_fact(doc, "endpoint_met", endpoint_met, "boolean", endpoint_met_evidence, endpoint_met_confidence, "endpoint_direction_regex"))

    for name, value, unit, evidence, confidence, method in extract_statistical_facts(doc_text):
        facts.append(_fact(doc, name, value, unit, evidence, confidence, method))

    safety_issue, safety_evidence, safety_confidence = extract_safety_language(doc_text)
    if safety_issue:
        facts.append(_fact(doc, "safety_issue", True, "boolean", safety_evidence, safety_confidence, "safety_language_regex", "safety_issue_present"))
        facts.append(_fact(doc, "adverse_event_language", safety_evidence[:500], "text", safety_evidence, safety_confidence, "safety_language_regex", "safety_issue_present"))

    if event_type in REGULATORY_DECISION_EVENT_TYPES or event_type == "trial_halt":
        action_map = {
            "fda_approval": "approval",
            "accelerated_approval": "accelerated_approval",
            "label_expansion": "label_expansion",
            "fda_complete_response_letter": "complete_response_letter",
            "fda_advisory_committee_positive": "advisory_committee_positive",
            "fda_advisory_committee_negative": "advisory_committee_negative",
            "priority_review": "priority_review",
            "breakthrough_designation": "breakthrough_designation",
            "fast_track_designation": "fast_track_designation",
            "orphan_drug_designation": "orphan_drug_designation",
            "trial_halt": "clinical_hold_or_trial_halt",
        }
        facts.append(_fact(doc, "fda_action", action_map.get(event_type, event_type), "category", event_evidence, event_confidence, "event_type_map", quality_flags))

    if event_type in APPROVAL_OR_LABEL_EVENT_TYPES:
        facts.append(_fact(doc, "approval_status", "approved", "category", event_evidence, event_confidence, "event_type_map"))
    elif event_type == "fda_complete_response_letter":
        facts.append(_fact(doc, "approval_status", "complete_response_letter", "category", event_evidence, event_confidence, "event_type_map"))
        facts.append(_fact(doc, "complete_response_letter_flag", True, "boolean", event_evidence, event_confidence, "event_type_map"))
    if event_type == "accelerated_approval":
        facts.append(_fact(doc, "accelerated_approval_flag", True, "boolean", event_evidence, event_confidence, "event_type_map"))
    if event_type == "label_expansion":
        facts.append(_fact(doc, "label_expansion_flag", True, "boolean", event_evidence, event_confidence, "event_type_map"))

    vote_for, vote_against, vote_evidence = _adcom_votes(doc_text)
    if vote_for is not None and vote_against is not None:
        facts.append(_fact(doc, "advisory_committee_vote_for", float(vote_for), "count", vote_evidence, 0.90, "adcom_vote_regex"))
        facts.append(_fact(doc, "advisory_committee_vote_against", float(vote_against), "count", vote_evidence, 0.90, "adcom_vote_regex"))

    pdufa_date, pdufa_evidence, pdufa_confidence = extract_pdufa_date(doc_text)
    if pdufa_date:
        facts.append(_fact(doc, "pdufa_date", pdufa_date, "date", pdufa_evidence, pdufa_confidence, "pdufa_date_regex"))

    asset_count, pipeline_evidence, pipeline_confidence = extract_pipeline_concentration(doc_text)
    if pipeline_evidence:
        if pd.notna(asset_count):
            facts.append(_fact(doc, "affected_pipeline_asset_count", asset_count, "count", pipeline_evidence, pipeline_confidence, "pipeline_concentration_language"))
        facts.append(
            _fact(
                doc,
                "company_pipeline_concentration_notes",
                pipeline_evidence[:500],
                "text",
                pipeline_evidence,
                pipeline_confidence,
                "pipeline_concentration_language",
                "requires_pipeline_concentration_review",
            )
        )

    if quality_flags:
        facts.append(_fact(doc, "parser_quality_flags", ";".join(sorted(set(quality_flags))), "text", event_evidence, 0.75, "quality_flag_rules", quality_flags))
    return _dedupe_facts(facts)


def parse_biotech_catalyst_manifest(
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
        for fact in parse_biotech_catalyst_document(doc):
            if fact.confidence >= min_confidence:
                rows.append(fact.to_dict())
    facts = pd.DataFrame(rows)
    for col in BIOTECH_FACT_COLUMNS:
        if col not in facts.columns:
            facts[col] = pd.Series(dtype=object)
    facts = facts[BIOTECH_FACT_COLUMNS + [c for c in facts.columns if c not in BIOTECH_FACT_COLUMNS]]
    if not facts.empty:
        facts = facts.sort_values(["ticker", "event_time", "event_id", "fact_name"]).reset_index(drop=True)
    ensure_parent(facts_out)
    facts.to_csv(facts_out, index=False)

    features = pivot_biotech_catalyst_facts(facts, features_out, min_confidence=usable_confidence)
    events = biotech_catalyst_features_to_events(features, events_out)
    return facts, features, events


def derive_biotech_catalyst_fields(row: dict | pd.Series) -> dict[str, object]:
    event_type = str(row.get("event_type") or row.get("biotech_catalyst_event_type") or "unknown").strip().lower()
    endpoint_met = _bool_or_na(row.get("endpoint_met"))
    safety_issue = _bool_value(row.get("safety_issue", False))

    clinical_readout = event_type in READOUT_EVENT_TYPES
    regulatory_decision = event_type in REGULATORY_DECISION_EVENT_TYPES
    designation_only = event_type in DESIGNATION_ONLY_EVENT_TYPES
    approval_or_label = event_type in APPROVAL_OR_LABEL_EVENT_TYPES
    safety_negative = event_type == "safety_signal" or safety_issue
    trial_failure = event_type in {"endpoint_failure", "trial_halt", "trial_discontinuation"} or endpoint_met is False
    trial_success = event_type == "endpoint_success" or (endpoint_met is True and clinical_readout and not safety_negative)

    binary = False
    if event_type in APPROVAL_OR_LABEL_EVENT_TYPES | {"fda_complete_response_letter", "fda_advisory_committee_positive", "fda_advisory_committee_negative"}:
        binary = True
    if event_type in {"phase_2_readout", "phase_3_readout", "pivotal_trial_readout"} and endpoint_met is not None:
        binary = True
    if event_type == "phase_1_readout" and (endpoint_met is not None or safety_negative):
        binary = True
    if event_type in {"trial_halt", "trial_discontinuation", "safety_signal", "endpoint_failure", "endpoint_success"}:
        binary = True
    if designation_only:
        binary = False

    if event_type in {"fda_complete_response_letter", "fda_advisory_committee_negative", "trial_halt", "trial_discontinuation", "safety_signal", "endpoint_failure"} or endpoint_met is False:
        direction = "negative"
    elif event_type in APPROVAL_OR_LABEL_EVENT_TYPES | {"fda_advisory_committee_positive", "endpoint_success"} or trial_success or designation_only:
        direction = "positive"
    elif clinical_readout:
        direction = "mixed"
    else:
        direction = "unknown"
    if trial_success and safety_negative:
        direction = "mixed"

    if event_type in {"fda_complete_response_letter", "phase_3_readout", "pivotal_trial_readout", "trial_halt", "trial_discontinuation", "endpoint_failure"}:
        materiality_pre_price = "high"
        numeric_materiality = 0.82
    elif event_type in APPROVAL_OR_LABEL_EVENT_TYPES | {"fda_advisory_committee_positive", "fda_advisory_committee_negative", "phase_2_readout", "safety_signal", "endpoint_success"}:
        materiality_pre_price = "medium"
        numeric_materiality = 0.68
    elif designation_only or event_type == "phase_1_readout":
        materiality_pre_price = "low"
        numeric_materiality = 0.38
    else:
        materiality_pre_price = "unknown"
        numeric_materiality = 0.45

    flags = set()
    existing_flags = str(row.get("parser_quality_flags", "") or "")
    for flag in existing_flags.split(";"):
        if flag.strip():
            flags.add(flag.strip())
    if designation_only:
        flags.add("designation_only_weaker_signal")
    if clinical_readout and endpoint_met is None:
        flags.add("endpoint_direction_unclear")
    if safety_negative:
        flags.add("safety_issue_present")
    if event_type != "unknown":
        flags.add("requires_pipeline_concentration_review")

    return {
        "biotech_catalyst_event_type": event_type,
        "binary_catalyst_flag": bool(binary),
        "clinical_trial_readout_flag": bool(clinical_readout),
        "regulatory_decision_flag": bool(regulatory_decision),
        "designation_only_flag": bool(designation_only),
        "safety_negative_flag": bool(safety_negative),
        "approval_or_label_expansion_flag": bool(approval_or_label),
        "trial_failure_flag": bool(trial_failure),
        "trial_success_flag": bool(trial_success),
        "pipeline_concentration_required_flag": bool(event_type != "unknown"),
        "event_direction_pre_price": direction,
        "materiality_pre_price": materiality_pre_price,
        "materiality": numeric_materiality,
        "label_quality": "machine_candidate",
        "evidence_status": "source_backed" if str(row.get("source_evidence_text", "") or row.get("event_type_evidence", "")).strip() else "needs_evidence_review",
        "parser_quality_flags": ";".join(sorted(flags)),
    }


def pivot_biotech_catalyst_facts(facts: pd.DataFrame, out_path: str | Path | None = None, *, min_confidence: float = 0.70) -> pd.DataFrame:
    if facts.empty:
        out = pd.DataFrame(columns=BIOTECH_FEATURE_COLUMNS)
    else:
        usable = facts[pd.to_numeric(facts["confidence"], errors="coerce") >= float(min_confidence)].copy()
        rows: list[dict[str, object]] = []
        for event_id, group in usable.groupby("event_id", sort=False):
            event_fact = group[group["fact_name"] == "event_type"].sort_values("confidence", ascending=False).head(1)
            source_evidence = ""
            if not event_fact.empty:
                source_evidence = str(event_fact.iloc[0].get("source_evidence_text", "") or event_fact.iloc[0].get("evidence_text", ""))
            row: dict[str, object] = {
                "event_id": event_id,
                "ticker": group["ticker"].iloc[0],
                "event_time": group["event_time"].iloc[0],
                "source_doc_ids": ";".join(sorted(group["source_doc_id"].astype(str).unique())),
                "usable_fact_count": int(len(group)),
                "source_type": group["source_type"].iloc[0],
                "source_url": group["source_url"].iloc[0],
                "source_evidence_text": source_evidence,
            }
            for _, fact in group.sort_values("confidence", ascending=False).drop_duplicates("fact_name").iterrows():
                name = fact["fact_name"]
                row[name] = fact["value"]
                row[f"{name}_confidence"] = fact["confidence"]
                row[f"{name}_evidence"] = fact.get("source_evidence_text", fact.get("evidence_text", ""))
            row.update(derive_biotech_catalyst_fields(row))
            rows.append(row)
        out = pd.DataFrame(rows)
        for col in BIOTECH_FEATURE_COLUMNS:
            if col not in out.columns:
                out[col] = pd.Series(dtype=object)
        out = out[BIOTECH_FEATURE_COLUMNS + [c for c in out.columns if c not in BIOTECH_FEATURE_COLUMNS]]
    if out_path:
        ensure_parent(out_path)
        out.to_csv(out_path, index=False)
    return out


def biotech_catalyst_features_to_events(features: pd.DataFrame, out_path: str | Path) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, row in features.iterrows():
        event_type = str(row.get("biotech_catalyst_event_type") or row.get("event_type") or "unknown")
        ticker = str(row.get("ticker", "")).upper()
        regulatory = _bool_value(row.get("regulatory_decision_flag", False))
        clinical = _bool_value(row.get("clinical_trial_readout_flag", False))
        generic_event_type = "regulatory" if regulatory else "clinical_trial" if clinical else "biotech_catalyst"
        direction = str(row.get("event_direction_pre_price", "unknown") or "unknown")
        materiality_pre = str(row.get("materiality_pre_price", "unknown") or "unknown")
        rows.append(
            {
                "event_id": row["event_id"],
                "ticker": ticker,
                "event_time": row["event_time"],
                "event_type": generic_event_type,
                "summary": f"{ticker} {event_type.replace('_', ' ')} biotech catalyst candidate from source document.",
                "event_subtype": event_type,
                "event_family": BIOTECH_CATALYST_DOMAIN,
                "source_type": row.get("source_type", "source_document"),
                "source_url": row.get("source_url", ""),
                "release_session": "unknown",
                "expectedness": "unknown",
                "surprise_direction": direction,
                "surprise_magnitude": materiality_pre,
                "materiality": row.get("materiality", 0.45),
                "sector_benchmark": "",
                "notes": "Biotech catalyst parser candidate; review source facts, exact timestamp/session, expectation context, pipeline concentration, and materiality before modeling.",
                "event_direction_pre_price": direction,
                "materiality_pre_price": materiality_pre,
                "label_quality": row.get("label_quality", "machine_candidate"),
                "evidence_status": row.get("evidence_status", "source_backed"),
                "review_status": "unreviewed",
                "drop_reason": "",
                "review_notes": "",
                **{
                    c: row.get(c, "")
                    for c in features.columns
                    if c
                    not in {
                        "ticker",
                        "event_id",
                        "event_time",
                        "source_type",
                        "source_url",
                        "event_type",
                        "materiality",
                        "label_quality",
                        "evidence_status",
                    }
                },
            }
        )
    make_event_template(out_path, rows)
    out = pd.read_csv(out_path)
    review_columns = [
        "biotech_catalyst_event_type",
        "clinical_trial_readout_flag",
        "regulatory_decision_flag",
        "binary_catalyst_flag",
        "event_direction_pre_price",
        "materiality_pre_price",
        "label_quality",
        "evidence_status",
        "review_status",
        "drop_reason",
        "review_notes",
    ]
    for col in review_columns:
        if col not in out.columns:
            out[col] = pd.Series(dtype=object)
    if rows:
        out.to_csv(out_path, index=False)
    else:
        out = out[list(out.columns)]
        out.to_csv(out_path, index=False)
    return out


def _combine_diagnostics(target: IngestionDiagnostics, source: IngestionDiagnostics) -> None:
    target.rows_total += source.rows_total
    target.rows_written += source.rows_written
    target.rows_skipped += source.rows_skipped
    target.downloaded += source.downloaded
    target.local_files_read += source.local_files_read
    target.inline_rows_read += source.inline_rows_read
    target.text_chars_total += source.text_chars_total
    for reason, count in source.skipped_reasons.items():
        target.skipped_reasons[reason] = target.skipped_reasons.get(reason, 0) + int(count)


def _load_manual_source_manifest(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    for col in SOURCE_DOC_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[SOURCE_DOC_COLUMNS + [c for c in df.columns if c not in SOURCE_DOC_COLUMNS]].copy()
    df["event_type"] = df["event_type"].replace("", "regulatory").fillna("regulatory")
    df["event_subtype"] = df["event_subtype"].replace("", "biotech_fda_clinical_candidate").fillna("biotech_fda_clinical_candidate")
    df["source_type"] = df["source_type"].replace("", "company_press_release").fillna("company_press_release")
    df["notes"] = df["notes"].fillna("").astype(str) + " biotech_fda_clinical_catalyst_manual_source=true"
    return df


def build_biotech_catalyst_source_documents(
    client: SecClient | None,
    tickers: list[str],
    out_manifest: str | Path,
    docs_dir: str | Path,
    *,
    start: str | None = None,
    end: str | None = None,
    forms: list[str] | None = None,
    item_filter: str = BIOTECH_CATALYST_8K_ITEMS,
    limit_per_ticker: int | None = None,
    sector_benchmark: str = "",
    source_manifests: list[str | Path] | None = None,
    include_sec: bool = True,
    overwrite: bool = False,
    min_text_chars: int = 40,
) -> tuple[pd.DataFrame, IngestionDiagnostics]:
    """Build a source-document manifest for biotech FDA/clinical catalysts.

    The automated first pass is SEC-centered because 8-K timestamps and exhibits
    are auditable. Company press releases, FDA pages, and ClinicalTrials.gov rows
    should be added through source-document manifests with the standard columns.
    """
    out_manifest = Path(out_manifest)
    combined = IngestionDiagnostics()
    frames: list[pd.DataFrame] = []
    tmp_paths: list[Path] = []

    if include_sec and tickers:
        if client is None:
            raise ValueError("A SecClient is required when include_sec=True and tickers are supplied")
        forms = [f.upper().strip() for f in (forms or list(BIOTECH_SEC_FORMS)) if str(f).strip()]
        for ticker in tickers:
            tmp = out_manifest.parent / f".{out_manifest.stem}_{ticker.upper()}_biotech_sec_tmp.csv"
            tmp_paths.append(tmp)
            try:
                df, diag = build_sec_source_document_manifest(
                    client,
                    tickers=[ticker.upper()],
                    out_manifest=tmp,
                    docs_dir=docs_dir,
                    forms=forms,
                    start=start,
                    end=end,
                    item_filter=None if str(item_filter).lower() in {"", "none", "all"} else item_filter,
                    limit_per_ticker=limit_per_ticker,
                    include_primary=True,
                    include_exhibits=True,
                    exhibit_pattern=BIOTECH_CATALYST_EXHIBIT_PATTERN,
                    sector_benchmark=sector_benchmark,
                    overwrite=overwrite,
                    min_text_chars=min_text_chars,
                )
            except Exception as exc:  # pragma: no cover - exact SEC/ticker failures vary
                combined.add_skip(f"sec ticker error: {type(exc).__name__}")
                continue
            if not df.empty:
                df = df.copy()
                df["event_type"] = "regulatory"
                df["event_subtype"] = "biotech_fda_clinical_candidate"
                df["notes"] = df["notes"].fillna("").astype(str) + " biotech_fda_clinical_catalyst_sec_candidate=true"
                frames.append(df)
            _combine_diagnostics(combined, diag)

    for manifest in source_manifests or []:
        try:
            manual = _load_manual_source_manifest(manifest)
        except Exception as exc:  # pragma: no cover - manifest errors vary
            combined.add_skip(f"manual manifest error: {type(exc).__name__}")
            continue
        frames.append(manual)
        combined.rows_total += int(len(manual))
        combined.rows_written += int(len(manual))

    out = pd.concat([f for f in frames if not f.empty], ignore_index=True, sort=False) if frames else pd.DataFrame(columns=SOURCE_DOC_COLUMNS)
    for col in SOURCE_DOC_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    if not out.empty:
        out = out.drop_duplicates(["source_doc_id"]).sort_values(["ticker", "event_time", "source_doc_id"]).reset_index(drop=True)
    out = out[SOURCE_DOC_COLUMNS + [c for c in out.columns if c not in SOURCE_DOC_COLUMNS]]
    ensure_parent(out_manifest)
    out.to_csv(out_manifest, index=False)
    for tmp in tmp_paths:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    combined.rows_written = int(len(out))
    return out, combined


def make_biotech_source_manifest_template(out_path: str | Path) -> pd.DataFrame:
    return make_source_docs_template(out_path, rows=[])


def validate_biotech_catalyst_parser(
    facts: pd.DataFrame,
    gold: pd.DataFrame,
    out_errors: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    if gold.empty:
        errors = pd.DataFrame(columns=["event_id", "fact_name", "expected_value", "actual_value", "unit", "status"])
        return errors, {"gold_rows": 0, "status": "no_gold_rows", "parser_audit_pass": False}

    pred = facts.copy()
    pred["confidence"] = pd.to_numeric(pred.get("confidence"), errors="coerce")
    pred = pred.sort_values("confidence", ascending=False).drop_duplicates(["event_id", "fact_name"], keep="first")
    key_cols = ["event_id", "fact_name"]
    merged = gold.merge(pred, on=key_cols, how="left", suffixes=("_gold", "_pred"))
    tolerance_by_unit = {"number": 0.0001, "ratio": 0.0001, "proportion": 0.0001, "count": 0.0, "boolean": 0.0}

    rows: list[dict[str, object]] = []
    for _, row in merged.iterrows():
        unit = str(row.get("unit_gold") or row.get("unit") or row.get("unit_pred") or "").strip()
        expected_raw = row.get("expected_value")
        actual_raw = row.get("value")
        expected_present = _bool_value(row.get("expected_present", True))
        tolerance_raw = pd.to_numeric(pd.Series([row.get("tolerance")]), errors="coerce").iloc[0]
        tolerance = float(tolerance_raw) if pd.notna(tolerance_raw) else float(tolerance_by_unit.get(unit, 0.0))

        if not expected_present:
            actual_text = _norm_space(actual_raw).lower() if pd.notna(actual_raw) else ""
            fact_name = _norm_space(row.get("fact_name")).lower()
            if fact_name == "event_type":
                status = "ok" if actual_text in {"", "unknown", "none", "nan"} else "false_positive"
            else:
                status = "ok" if pd.isna(actual_raw) else "false_positive"
            abs_error = np.nan
        elif unit in {"category", "text", "identifier", "date"}:
            expected = _norm_space(expected_raw).lower()
            actual = _norm_space(actual_raw).lower() if pd.notna(actual_raw) else ""
            status = "ok" if actual == expected else "wrong_value" if actual else "missed"
            abs_error = np.nan
        elif unit == "boolean":
            expected = _bool_value(expected_raw)
            actual = _bool_value(actual_raw) if pd.notna(actual_raw) else None
            status = "ok" if actual == expected else "wrong_value" if actual is not None else "missed"
            abs_error = np.nan
        else:
            expected_num = pd.to_numeric(pd.Series([expected_raw]), errors="coerce").iloc[0]
            actual_num = pd.to_numeric(pd.Series([actual_raw]), errors="coerce").iloc[0]
            if pd.isna(actual_num):
                status = "missed"
                abs_error = np.nan
            else:
                abs_error = abs(float(actual_num) - float(expected_num))
                status = "ok" if abs_error <= tolerance else "wrong_value"
        rows.append(
            {
                "event_id": row.get("event_id"),
                "fact_name": row.get("fact_name"),
                "expected_value": expected_raw,
                "actual_value": actual_raw,
                "unit": unit,
                "tolerance": tolerance,
                "abs_error": abs_error,
                "status": status,
                "confidence": row.get("confidence"),
                "gold_category": row.get("gold_category", ""),
                "source_evidence_text": row.get("source_evidence_text_pred", row.get("source_evidence_text", row.get("evidence_text", ""))),
            }
        )

    errors = pd.DataFrame(rows)

    def precision_for(mask: pd.Series) -> float:
        subset = errors[mask]
        if subset.empty:
            return 0.0
        correct = int((subset["status"] == "ok").sum())
        return correct / len(subset)

    by_fact: dict[str, dict[str, object]] = {}
    for fact_name, group in errors.groupby("fact_name"):
        total = int(len(group))
        ok = int((group["status"] == "ok").sum())
        by_fact[fact_name] = {"gold_rows": total, "correct": ok, "precision_on_gold": ok / total if total else 0.0}

    expected_values = errors["expected_value"].fillna("").astype(str).str.lower()
    actual_values = errors["actual_value"].fillna("").astype(str).str.lower()
    event_type_mask = errors["fact_name"].eq("event_type")
    regulatory_mask = event_type_mask & expected_values.isin(REGULATORY_DECISION_EVENT_TYPES)
    endpoint_mask = errors["fact_name"].isin(["endpoint_met", "p_value", "hazard_ratio", "response_rate", "overall_survival", "progression_free_survival"])

    designation_mistaken_for_approval = bool(
        (
            event_type_mask
            & expected_values.isin(DESIGNATION_ONLY_EVENT_TYPES)
            & actual_values.isin(APPROVAL_OR_LABEL_EVENT_TYPES)
            & errors["status"].ne("ok")
        ).any()
    )
    enrollment_mistaken_for_readout = bool(
        (
            event_type_mask
            & errors.get("gold_category", pd.Series("", index=errors.index)).fillna("").astype(str).str.lower().eq("enrollment_update")
            & actual_values.isin(READOUT_EVENT_TYPES)
        ).any()
    )
    publication_mistaken_for_readout = bool(
        (
            event_type_mask
            & errors.get("gold_category", pd.Series("", index=errors.index)).fillna("").astype(str).str.lower().eq("publication_conference_notice")
            & actual_values.isin(READOUT_EVENT_TYPES)
        ).any()
    )
    gold_category = errors.get("gold_category", pd.Series("", index=errors.index)).fillna("").astype(str).str.lower()
    hard_negative_categories = {
        "enrollment_update",
        "publication_conference_notice",
        "pipeline_update",
        "pipeline_table",
        "investor_deck_pipeline_table",
        "trial_initiation",
        "trial_design_protocol",
        "previously_announced",
        "fda_regulatory_decision_false_positive",
    }
    hard_negative_mistaken_for_catalyst = bool(
        (
            event_type_mask
            & gold_category.isin(hard_negative_categories)
            & actual_values.isin(BINARY_CATALYST_EVENT_TYPES | DESIGNATION_ONLY_EVENT_TYPES)
        ).any()
    )
    pipeline_table_mistaken_for_catalyst = bool(
        (
            event_type_mask
            & gold_category.isin({"pipeline_table", "investor_deck_pipeline_table"})
            & actual_values.isin(BINARY_CATALYST_EVENT_TYPES | DESIGNATION_ONLY_EVENT_TYPES)
        ).any()
    )
    trial_initiation_mistaken_for_readout = bool(
        (event_type_mask & gold_category.eq("trial_initiation") & actual_values.isin(READOUT_EVENT_TYPES)).any()
    )
    trial_design_mistaken_for_readout = bool(
        (event_type_mask & gold_category.eq("trial_design_protocol") & actual_values.isin(READOUT_EVENT_TYPES)).any()
    )
    previously_announced_mistaken_for_catalyst = bool(
        (event_type_mask & gold_category.eq("previously_announced") & actual_values.isin(BINARY_CATALYST_EVENT_TYPES | DESIGNATION_ONLY_EVENT_TYPES)).any()
    )

    metrics = {
        "gold_rows": int(len(errors)),
        "correct_rows": int((errors["status"] == "ok").sum()),
        "row_accuracy": float((errors["status"] == "ok").mean()) if len(errors) else 0.0,
        "event_type_precision": precision_for(event_type_mask),
        "drug_asset_indication_precision": precision_for(errors["fact_name"].isin(["drug_asset", "indication"])),
        "trial_phase_precision": precision_for(errors["fact_name"].eq("trial_phase")),
        "endpoint_success_failure_precision": precision_for(errors["fact_name"].eq("endpoint_met")),
        "endpoint_statistical_precision": precision_for(endpoint_mask),
        "regulatory_decision_precision": precision_for(regulatory_mask),
        "no_designation_only_event_mistaken_for_approval": not designation_mistaken_for_approval,
        "no_enrollment_update_event_mistaken_for_readout": not enrollment_mistaken_for_readout,
        "no_publication_conference_notice_mistaken_for_new_topline_result": not publication_mistaken_for_readout,
        "no_hard_negative_mistaken_for_binary_catalyst": not hard_negative_mistaken_for_catalyst,
        "no_investor_deck_pipeline_table_mistaken_for_new_catalyst": not pipeline_table_mistaken_for_catalyst,
        "no_trial_initiation_mistaken_for_readout": not trial_initiation_mistaken_for_readout,
        "no_trial_design_protocol_mistaken_for_readout": not trial_design_mistaken_for_readout,
        "no_previously_announced_result_mistaken_for_new_catalyst": not previously_announced_mistaken_for_catalyst,
        "by_fact": by_fact,
    }
    gates = {
        "gold_rows_60": metrics["gold_rows"] >= 60,
        "event_type_precision_95": metrics["event_type_precision"] >= 0.95,
        "drug_asset_indication_precision_90": metrics["drug_asset_indication_precision"] >= 0.90,
        "trial_phase_precision_90": metrics["trial_phase_precision"] >= 0.90,
        "endpoint_success_failure_precision_90": metrics["endpoint_success_failure_precision"] >= 0.90,
        "regulatory_decision_precision_95": metrics["regulatory_decision_precision"] >= 0.95,
        "no_designation_only_event_mistaken_for_approval": metrics["no_designation_only_event_mistaken_for_approval"],
        "no_enrollment_update_event_mistaken_for_readout": metrics["no_enrollment_update_event_mistaken_for_readout"],
        "no_publication_conference_notice_mistaken_for_new_topline_result": metrics["no_publication_conference_notice_mistaken_for_new_topline_result"],
        "no_hard_negative_mistaken_for_binary_catalyst": metrics["no_hard_negative_mistaken_for_binary_catalyst"],
        "no_investor_deck_pipeline_table_mistaken_for_new_catalyst": metrics["no_investor_deck_pipeline_table_mistaken_for_new_catalyst"],
        "no_trial_initiation_mistaken_for_readout": metrics["no_trial_initiation_mistaken_for_readout"],
        "no_trial_design_protocol_mistaken_for_readout": metrics["no_trial_design_protocol_mistaken_for_readout"],
        "no_previously_announced_result_mistaken_for_new_catalyst": metrics["no_previously_announced_result_mistaken_for_new_catalyst"],
    }
    metrics["gates"] = gates
    metrics["parser_audit_pass"] = bool(all(gates.values()))
    if out_errors:
        ensure_parent(out_errors)
        errors.to_csv(out_errors, index=False)
    return errors, metrics


def build_biotech_catalyst_gold_template(facts: pd.DataFrame, out_path: str | Path, *, target_rows: int = 70) -> pd.DataFrame:
    if facts.empty:
        out = pd.DataFrame(columns=["event_id", "fact_name", "expected_value", "unit", "tolerance", "expected_present", "gold_category", "source_evidence_text", "review_status", "review_notes"])
    else:
        df = facts.copy()
        df["confidence"] = pd.to_numeric(df.get("confidence"), errors="coerce").fillna(0.0)
        df = df.sort_values("confidence", ascending=False)

        def take(mask: pd.Series, n: int, category: str) -> pd.DataFrame:
            subset = df[mask].drop_duplicates(["event_id", "fact_name"]).head(n).copy()
            subset["gold_category"] = category
            return subset

        event_values = df["value"].fillna("").astype(str).str.lower()
        flag_text = df.get("parser_quality_flags", pd.Series("", index=df.index)).fillna("").astype(str).str.lower()
        hard_negative_mask = (
            df["fact_name"].eq("event_type")
            & event_values.eq("unknown")
            & flag_text.str.contains(
                "enrollment_update_not_binary|publication_or_conference_notice_not_topline|pipeline_update_not_binary|trial_initiation_not_binary|trial_design_not_binary|previously_announced_not_new|background_approval_language_not_decision|boilerplate_or_risk_factor_not_event|pipeline_table_requires_new_result",
                regex=True,
            )
        )
        selected = [
            take(df["fact_name"].eq("event_type") & event_values.isin(REGULATORY_DECISION_EVENT_TYPES), 15, "fda_regulatory_decision"),
            take(df["fact_name"].eq("event_type") & event_values.isin({"phase_2_readout", "phase_3_readout", "pivotal_trial_readout"}), 15, "phase_2_3_readout"),
            take(df["fact_name"].eq("event_type") & event_values.isin({"trial_halt", "trial_discontinuation", "safety_signal", "endpoint_failure"}), 10, "trial_halt_failure_safety"),
            take(df["fact_name"].eq("event_type") & event_values.isin(DESIGNATION_ONLY_EVENT_TYPES | {"accelerated_approval"}), 10, "designation_priority_accelerated"),
            take(df["fact_name"].isin(["endpoint_met", "p_value", "hazard_ratio", "response_rate", "overall_survival", "progression_free_survival"]), 10, "endpoint_statistical_fact"),
            take(hard_negative_mask, 10, "hard_negative_non_catalyst"),
        ]
        out = pd.concat([s for s in selected if not s.empty], ignore_index=True) if selected else pd.DataFrame()
        if len(out) < target_rows:
            existing = set(zip(out.get("event_id", pd.Series(dtype=str)).astype(str), out.get("fact_name", pd.Series(dtype=str)).astype(str)))
            filler = df[~df.apply(lambda r: (str(r.get("event_id")), str(r.get("fact_name"))) in existing, axis=1)].drop_duplicates(["event_id", "fact_name"]).head(target_rows - len(out)).copy()
            filler["gold_category"] = "filler_high_confidence_fact"
            out = pd.concat([out, filler], ignore_index=True, sort=False)
        out = out.head(target_rows).copy()
        expected_present = ~out.get("gold_category", pd.Series("", index=out.index)).astype(str).str.lower().isin({"hard_negative_non_catalyst"})
        out = pd.DataFrame(
            {
                "event_id": out.get("event_id", ""),
                "fact_name": out.get("fact_name", ""),
                "expected_value": out.get("value", ""),
                "unit": out.get("unit", ""),
                "tolerance": "",
                "expected_present": expected_present,
                "gold_category": out.get("gold_category", ""),
                "source_evidence_text": out.get("source_evidence_text", out.get("evidence_text", "")),
                "review_status": "needs_human_review",
                "review_notes": "Confirm this parser-proposed value against the source before using it as gold.",
            }
        )
    ensure_parent(out_path)
    out.to_csv(out_path, index=False)
    return out


def write_biotech_catalyst_parser_audit_report(report: dict[str, object], errors: pd.DataFrame, out_path: str | Path) -> Path:
    out = ensure_parent(out_path)
    lines = [
        "# Biotech Catalyst Parser Audit Report",
        "",
        "This validates parser facts against a human-reviewed gold set. It is a parser-quality report, not a model result.",
        "",
        "## Metrics",
        "",
    ]
    for key in [
        "gold_rows",
        "correct_rows",
        "row_accuracy",
        "event_type_precision",
        "drug_asset_indication_precision",
        "trial_phase_precision",
        "endpoint_success_failure_precision",
        "endpoint_statistical_precision",
        "regulatory_decision_precision",
        "parser_audit_pass",
        "status",
    ]:
        if key in report:
            value = report[key]
            lines.append(f"- {key}: {value:.3f}" if isinstance(value, float) else f"- {key}: {value}")
    lines.extend(["", "## Gates", ""])
    for gate, passed in (report.get("gates", {}) or {}).items():
        lines.append(f"- {gate}: {'PASS' if passed else 'FAIL'}")
    lines.extend(["", "## By Fact", ""])
    for fact_name, metrics in (report.get("by_fact", {}) or {}).items():
        lines.append(f"- {fact_name}: {metrics}")
    bad = errors[errors["status"] != "ok"] if not errors.empty and "status" in errors.columns else pd.DataFrame()
    if not bad.empty:
        lines.extend(["", "## Non-OK Rows", ""])
        for _, row in bad.head(75).iterrows():
            lines.append(f"- {row['event_id']} / {row['fact_name']}: {row['status']} expected={row['expected_value']} actual={row['actual_value']}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def _reviewed_usable_events(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    review_status = events.get("review_status", pd.Series([""] * len(events), index=events.index)).fillna("").astype(str).str.lower()
    usable = events[~review_status.isin({"rejected", "drop", "dropped"})].copy()
    usable_status = usable.get("review_status", pd.Series([""] * len(usable), index=usable.index)).fillna("").astype(str).str.lower()
    usable = usable[usable_status.isin({"reviewed", "curated", "approved"})].copy()
    event_type = usable.get("biotech_catalyst_event_type", usable.get("event_subtype", pd.Series("", index=usable.index))).fillna("").astype(str).str.lower()
    return usable[event_type.ne("unknown") & event_type.ne("")].copy()


def biotech_catalyst_readiness_summary(
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
            "binary_catalyst_events_60": False,
            "negative_catalyst_events_30": False,
            "positive_catalyst_events_30": False,
            "market_cap_context_rows_40": False,
            "pre_event_runup_context_rows_40": False,
            "event_timestamps_clear": False,
            "likely_oos_predictions_30": False,
            "placebo_peer_controls_ready": False,
            "parser_audit_pass": False,
        }
        return {
            "source_documents_recovered": source_doc_rows,
            "parsed_event_rows": 0,
            "reviewed_usable_rows": 0,
            "binary_catalyst_rows": 0,
            "fda_regulatory_decision_rows": 0,
            "phase_2_3_readout_rows": 0,
            "negative_catalyst_rows": 0,
            "positive_catalyst_rows": 0,
            "rows_with_market_cap_context": 0,
            "rows_with_pre_event_runup_context": 0,
            "rows_with_source_evidence": 0,
            "parser_audit_precision": "missing",
            "likely_oos_predictions_min_train": 0,
            "gates": gates,
            "top_missing_fields_blocking_modeling": list(gates),
            "decision": "continue corpus buildout",
            "reason": "no parsed event rows",
        }

    reviewed = _reviewed_usable_events(events)
    review_base = reviewed
    event_type = review_base.get("biotech_catalyst_event_type", review_base.get("event_subtype", pd.Series(dtype=str))).fillna("").astype(str).str.lower()
    direction = review_base.get("event_direction_pre_price", review_base.get("surprise_direction", pd.Series(dtype=str))).fillna("").astype(str).str.lower()
    binary = review_base.get("binary_catalyst_flag", pd.Series(False, index=review_base.index)).map(_bool_value)
    regulatory = review_base.get("regulatory_decision_flag", pd.Series(False, index=review_base.index)).map(_bool_value)
    readout = review_base.get("clinical_trial_readout_flag", pd.Series(False, index=review_base.index)).map(_bool_value)
    phase = review_base.get("trial_phase", pd.Series("", index=review_base.index)).fillna("").astype(str).str.lower()

    rows_with_source_evidence = int(
        review_base.get("source_evidence_text", pd.Series("", index=review_base.index)).fillna("").astype(str).str.strip().ne("").sum()
    )
    market_cap_col = review_base.get("market_cap_before_event", pd.Series(index=review_base.index, dtype=float))
    runup_col = review_base.get("pre_event_market_adjusted_return_20d", pd.Series(index=review_base.index, dtype=float))
    timestamps = pd.to_datetime(review_base.get("event_time", pd.Series(index=review_base.index, dtype=str)), errors="coerce")
    release_session = review_base.get("release_session", pd.Series("", index=review_base.index)).fillna("").astype(str).str.lower()
    clear_timestamps = timestamps.notna() & release_session.isin({"before_open", "intraday", "after_close"})
    sector_benchmark = review_base.get("sector_benchmark", pd.Series("", index=review_base.index)).fillna("").astype(str).str.strip()

    metrics: dict[str, object] = {
        "source_documents_recovered": source_doc_rows,
        "parsed_event_rows": int(len(events)),
        "reviewed_usable_rows": int(len(review_base)),
        "binary_catalyst_rows": int(binary.sum()),
        "fda_regulatory_decision_rows": int(regulatory.sum()),
        "phase_2_3_readout_rows": int((readout & phase.isin({"phase_2", "phase_2_3", "phase_3", "pivotal"})).sum()),
        "negative_catalyst_rows": int(direction.eq("negative").sum()),
        "positive_catalyst_rows": int(direction.eq("positive").sum()),
        "rows_with_market_cap_context": int(pd.to_numeric(market_cap_col, errors="coerce").notna().sum()),
        "rows_with_pre_event_runup_context": int(pd.to_numeric(runup_col, errors="coerce").notna().sum()),
        "rows_with_source_evidence": rows_with_source_evidence,
        "rows_with_clear_event_timestamps": int(clear_timestamps.sum()),
        "rows_with_sector_benchmark": int(sector_benchmark.ne("").sum()),
        "likely_oos_predictions_min_train": int(max(0, len(review_base) - int(min_train))),
    }

    gates = {
        "reviewed_usable_events_80_min": metrics["reviewed_usable_rows"] >= 80,
        "reviewed_usable_events_100_preferred": metrics["reviewed_usable_rows"] >= 100,
        "binary_catalyst_events_60": metrics["binary_catalyst_rows"] >= 60,
        "negative_catalyst_events_30": metrics["negative_catalyst_rows"] >= 30,
        "positive_catalyst_events_30": metrics["positive_catalyst_rows"] >= 30,
        "market_cap_context_rows_40": metrics["rows_with_market_cap_context"] >= 40,
        "pre_event_runup_context_rows_40": metrics["rows_with_pre_event_runup_context"] >= 40,
        "event_timestamps_clear": metrics["rows_with_clear_event_timestamps"] >= metrics["reviewed_usable_rows"] and metrics["reviewed_usable_rows"] > 0,
        "likely_oos_predictions_30": metrics["likely_oos_predictions_min_train"] >= 30,
        "placebo_peer_controls_ready": metrics["rows_with_sector_benchmark"] >= metrics["reviewed_usable_rows"] and metrics["reviewed_usable_rows"] > 0,
    }
    if parser_errors is not None:
        ok_count = int((parser_errors.get("status", pd.Series(dtype=str)) == "ok").sum()) if not parser_errors.empty else 0
        audit_rows = int(len(parser_errors))
        audit_precision = ok_count / audit_rows if audit_rows else 0.0
        metrics["parser_audit_rows"] = audit_rows
        metrics["parser_audit_precision"] = float(audit_precision)
        if {"fact_name", "gold_category", "actual_value"}.issubset(parser_errors.columns):
            event_type_errors = parser_errors[parser_errors["fact_name"].astype(str).eq("event_type")]
            event_type_ok = int(event_type_errors["status"].astype(str).eq("ok").sum()) if not event_type_errors.empty else 0
            event_type_precision = event_type_ok / len(event_type_errors) if len(event_type_errors) else 0.0
            actual_event_types = parser_errors["actual_value"].fillna("").astype(str).str.lower()
            gold_category = parser_errors["gold_category"].fillna("").astype(str).str.lower()
            designation_mistaken_for_approval = bool(
                (
                    gold_category.eq("designation_priority_accelerated")
                    & actual_event_types.isin(APPROVAL_OR_LABEL_EVENT_TYPES)
                    & parser_errors["status"].astype(str).ne("ok")
                ).any()
            )
            enrollment_mistaken_for_readout = bool((gold_category.eq("enrollment_update") & actual_event_types.isin(READOUT_EVENT_TYPES)).any())
            publication_mistaken_for_readout = bool((gold_category.eq("publication_conference_notice") & actual_event_types.isin(READOUT_EVENT_TYPES)).any())
            hard_negative_categories = {
                "enrollment_update",
                "publication_conference_notice",
                "pipeline_update",
                "pipeline_table",
                "investor_deck_pipeline_table",
                "trial_initiation",
                "trial_design_protocol",
                "previously_announced",
                "fda_regulatory_decision_false_positive",
                "hard_negative_non_catalyst",
            }
            hard_negative_mistaken_for_catalyst = bool(
                (gold_category.isin(hard_negative_categories) & actual_event_types.isin(BINARY_CATALYST_EVENT_TYPES | DESIGNATION_ONLY_EVENT_TYPES)).any()
            )
            pipeline_table_mistaken_for_catalyst = bool(
                (gold_category.isin({"pipeline_table", "investor_deck_pipeline_table"}) & actual_event_types.isin(BINARY_CATALYST_EVENT_TYPES | DESIGNATION_ONLY_EVENT_TYPES)).any()
            )
            metrics["parser_event_type_precision"] = float(event_type_precision)
            metrics["parser_enrollment_update_false_readout"] = enrollment_mistaken_for_readout
            metrics["parser_publication_notice_false_readout"] = publication_mistaken_for_readout
            metrics["parser_hard_negative_false_catalyst"] = hard_negative_mistaken_for_catalyst
            metrics["parser_pipeline_table_false_catalyst"] = pipeline_table_mistaken_for_catalyst
            gates["parser_audit_pass"] = bool(
                audit_rows >= 60
                and event_type_precision >= 0.95
                and audit_precision >= 0.90
                and not designation_mistaken_for_approval
                and not enrollment_mistaken_for_readout
                and not publication_mistaken_for_readout
                and not hard_negative_mistaken_for_catalyst
                and not pipeline_table_mistaken_for_catalyst
            )
        else:
            gates["parser_audit_pass"] = bool(audit_rows >= 60 and audit_precision >= 0.90)
    else:
        metrics["parser_audit_precision"] = "missing"
        gates["parser_audit_pass"] = False

    blockers = [gate for gate, passed in gates.items() if not passed]
    metrics["gates"] = gates
    metrics["top_missing_fields_blocking_modeling"] = blockers[:]
    if all(gates.values()):
        metrics["decision"] = "model-ready"
        metrics["reason"] = "reviewed corpus clears first-pass non-modeling readiness gates"
    elif not gates["parser_audit_pass"] and metrics["reviewed_usable_rows"] >= 40:
        metrics["decision"] = "parser not trusted"
        metrics["reason"] = "parser audit is missing or below gate"
    elif metrics["reviewed_usable_rows"] >= 80 and (
        not gates["market_cap_context_rows_40"] or not gates["pre_event_runup_context_rows_40"] or not gates["placebo_peer_controls_ready"]
    ):
        metrics["decision"] = "context insufficient"
        metrics["reason"] = "reviewed corpus size is plausible but context/control fields are incomplete"
    else:
        metrics["decision"] = "continue corpus buildout"
        metrics["reason"] = "readiness gates still failing: " + ", ".join(blockers)
    return metrics


def write_biotech_catalyst_readiness_report(
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
    summary = biotech_catalyst_readiness_summary(
        events,
        min_train=min_train,
        source_documents=source_documents,
        parser_errors=parser_errors,
    )
    out = ensure_parent(out_path)
    lines = [
        "# Biotech FDA / Clinical Catalyst Readiness Report",
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
    for key in [
        "source_documents_recovered",
        "parsed_event_rows",
        "reviewed_usable_rows",
        "binary_catalyst_rows",
        "fda_regulatory_decision_rows",
        "phase_2_3_readout_rows",
        "negative_catalyst_rows",
        "positive_catalyst_rows",
        "rows_with_market_cap_context",
        "rows_with_pre_event_runup_context",
        "rows_with_source_evidence",
        "parser_audit_precision",
        "parser_event_type_precision",
        "parser_enrollment_update_false_readout",
        "parser_publication_notice_false_readout",
        "parser_hard_negative_false_catalyst",
        "parser_pipeline_table_false_catalyst",
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
            "1. Small/mid-cap biotech, binary negative catalyst: expected negative abnormal return.",
            "2. Phase 3 or pivotal readout with endpoint met and no major safety issue: expected positive abnormal return, strongest for pipeline-concentrated companies.",
            "3. Complete response letter, trial halt, or endpoint failure: expected negative abnormal return.",
            "4. Designation-only events: expected weaker/noisier reaction than approvals/readouts.",
            "5. Positive catalyst after strong pre-event run-up: expected weaker reaction or sell-the-news risk.",
            "",
            "Do not model until every gate above passes and placebo/peer controls can be built.",
        ]
    )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
