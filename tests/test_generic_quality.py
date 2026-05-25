from __future__ import annotations

import json

from mre.generic.compatibility import CompatibilityDimension, CompatibilityReport
from mre.generic.quality import build_generic_quality_report


def test_generic_quality_report_review_yield_and_source_breakdowns(tmp_path):
    claims = [
        {
            "claim_id": "c1",
            "event_id": "e1",
            "field_name": "impact_language",
            "evidence_span_id": "s1",
            "review_status": "needs_review",
            "claim_kind": "source_assertion",
            "claim_truth_status": "asserted_by_source",
            "source_authority_level": "official_regulator",
            "source_role": "canonical",
            "source_system": "toy_source",
        },
        {
            "claim_id": "c2",
            "event_id": "e1",
            "field_name": "impact_language",
            "evidence_span_id": "s2",
            "review_status": "rejected",
            "claim_kind": "source_assertion",
            "claim_truth_status": "asserted_by_source",
            "source_authority_level": "unknown",
            "source_role": "early_signal",
            "source_system": "toy_source",
        },
        {"claim_id": "c3", "event_id": "e2", "field_name": "incident_mentioned", "evidence_span_id": "s3", "review_status": "machine_high_confidence"},
        {"claim_id": "c4", "event_id": "e2", "field_name": "incident_mentioned", "evidence_span_id": "", "review_status": "needs_review"},
    ]
    evidence = [{"evidence_span_id": "s1"}, {"evidence_span_id": "s2"}, {"evidence_span_id": "s3"}]
    review_queue = [
        {
            "claim_id": "c1",
            "review_status": "human_reviewed",
            "review_action": "accept",
            "issue_flags": "too_broad;needs_context",
            "review_time_seconds": 20,
            "parser_failure_reason": "none",
        },
        {
            "claim_id": "c2",
            "review_status": "rejected",
            "review_action": "reject",
            "issue_flags": "false_positive",
            "review_time_seconds": 40,
            "parser_failure_reason": "keyword",
        },
    ]
    compatibility = CompatibilityReport(
        plugin_name="toy",
        dimensions=[CompatibilityDimension(name="document_text_quality", score=0.8, basis="clean")],
        readiness={"exploration": 0.7},
    )
    out_json = tmp_path / "quality.json"
    out_md = tmp_path / "quality.md"

    report = build_generic_quality_report(
        events=[{"event_id": "e1"}, {"event_id": "e2"}],
        claims=claims,
        evidence_spans=evidence,
        review_queue=review_queue,
        compatibility_reports=[compatibility],
        out_json=out_json,
        out_md=out_md,
    )

    assert report["n_claims"] == 4
    assert report["n_human_reviewed_claims"] == 1
    assert report["n_machine_high_confidence_claims"] == 1
    assert report["n_rejected_claims"] == 1
    assert report["n_missing_evidence_claims"] == 1
    assert report["evidence_coverage_rate"] == 0.75
    assert report["reviewed_claim_yield_rate"] == 0.5
    assert report["median_review_time_seconds"] == 30.0
    assert report["average_review_time_seconds"] == 30.0
    assert report["issue_flag_counts"] == {"false_positive": 1, "needs_context": 1, "too_broad": 1}
    assert report["review_action_counts"] == {"accept": 1, "reject": 1}
    assert report["parser_failure_reason_counts"] == {"keyword": 1, "none": 1}
    assert report["claim_kind_counts"]["source_assertion"] == 2
    assert report["source_role_counts"] == {"canonical": 1, "early_signal": 1}
    assert report["compatibility_dimension_summary"]["document_text_quality"]["average"] == 0.8
    assert report["readiness_summary"]["exploration"]["average"] == 0.7
    assert out_json.exists()
    assert "Review Yield" in out_md.read_text(encoding="utf-8")
    json.loads(out_json.read_text(encoding="utf-8"))


def test_review_queue_overrides_claim_status_for_precision():
    report = build_generic_quality_report(
        events=[{"event_id": "e1"}],
        claims=[{"claim_id": "c1", "event_id": "e1", "field_name": "field", "evidence_span_id": "s1", "review_status": "needs_review"}],
        evidence_spans=[{"evidence_span_id": "s1"}],
        review_queue=[{"claim_id": "c1", "review_status": "human_reviewed"}],
    )

    assert report["field_precision_by_field_name"] == [
        {"field_name": "field", "accepted": 1, "rejected": 0, "reviewed_total": 1, "precision": 1.0}
    ]


def test_review_queue_string_fields_override_empty_float_columns():
    report = build_generic_quality_report(
        events=[{"event_id": "e1"}],
        claims=[
            {
                "claim_id": "c1",
                "event_id": "e1",
                "field_name": "field",
                "evidence_span_id": "s1",
                "review_status": "needs_review",
                "label_quality": None,
                "review_action": None,
            }
        ],
        evidence_spans=[{"evidence_span_id": "s1"}],
        review_queue=[
            {
                "claim_id": "c1",
                "review_status": "human_reviewed",
                "label_quality": "high",
                "review_action": "accept",
            }
        ],
    )

    assert report["n_human_reviewed_claims"] == 1
    assert report["review_action_counts"] == {"accept": 1}
