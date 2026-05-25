from __future__ import annotations

import json

from mre.generic.publishers import (
    build_generic_digest,
    build_generic_static_site,
    evidence_highlight_html,
    export_generic_api,
    merge_review_queue,
)


def _rows():
    events = [{"event_id": "e1", "event_family": "toy", "event_type": "incident", "status": "draft"}]
    claims = [
        {
            "claim_id": "c1",
            "event_id": "e1",
            "field_name": "impact_language",
            "value": "yes",
            "confidence": 0.8,
            "review_status": "needs_review",
            "label_quality": "",
            "claim_kind": "source_assertion",
            "claim_truth_status": "asserted_by_source",
            "source_role": "canonical",
            "source_authority_level": "official_regulator",
            "method": "toy",
            "evidence_span_id": "s1",
        },
        {
            "claim_id": "c2",
            "event_id": "e1",
            "field_name": "weak_claim",
            "value": "maybe",
            "confidence": 0.4,
            "review_status": "needs_review",
            "evidence_span_id": "s2",
        },
    ]
    evidence = [
        {"evidence_span_id": "s1", "source_doc_id": "doc1", "claim_id": "c1", "evidence_text": "affected <operations>", "start_char": 7, "end_char": 28},
        {"evidence_span_id": "s2", "source_doc_id": "doc1", "claim_id": "c2", "evidence_text": "weak text", "start_char": 0, "end_char": 4},
    ]
    review_queue = [
        {"claim_id": "c1", "review_status": "human_reviewed", "label_quality": "high"},
        {"claim_id": "c2", "review_status": "rejected", "label_quality": "low"},
    ]
    return events, claims, evidence, review_queue


def test_merge_review_queue_overrides_non_empty_values():
    _, claims, _, review_queue = _rows()
    merged = merge_review_queue(claims, review_queue)

    assert merged.loc[merged["claim_id"] == "c1", "review_status"].iloc[0] == "human_reviewed"
    assert merged.loc[merged["claim_id"] == "c2", "label_quality"].iloc[0] == "low"


def test_merge_review_queue_string_fields_override_empty_float_columns():
    claims = [
        {
            "claim_id": "c1",
            "review_status": "needs_review",
            "label_quality": None,
            "review_action": None,
        }
    ]
    review_queue = [
        {
            "claim_id": "c1",
            "review_status": "human_reviewed",
            "label_quality": "high",
            "review_action": "accept",
        }
    ]

    merged = merge_review_queue(claims, review_queue)

    assert merged.loc[0, "label_quality"] == "high"
    assert merged.loc[0, "review_action"] == "accept"


def test_evidence_highlight_html_escapes_and_marks():
    html = evidence_highlight_html("before <evidence> after", 7, 17, window=20)

    assert "<mark>&lt;evidence&gt;</mark>" in html
    assert evidence_highlight_html("short", 10, 12) == ""


def test_static_site_api_and_digest_outputs(tmp_path):
    events, claims, evidence, review_queue = _rows()
    source_texts = {"doc1": "prefix affected <operations> suffix"}

    site_outputs = build_generic_static_site(
        events=events,
        claims=claims,
        evidence_spans=evidence,
        review_queue=review_queue,
        source_texts=source_texts,
        out_dir=tmp_path / "site",
        title="Toy Evidence Dataset",
    )
    event_page = (tmp_path / "site" / "event" / "e1.html").read_text(encoding="utf-8")
    assert "human_reviewed" in event_page
    assert "rejected" in event_page
    assert "<mark>affected &lt;operations&gt;</mark>" in event_page
    assert site_outputs["event_pages"] == 1

    api_outputs = export_generic_api(
        events=events,
        claims=claims,
        evidence_spans=evidence,
        review_queue=review_queue,
        out_dir=tmp_path / "api",
        include_evidence=False,
    )
    parsed_events = json.loads((tmp_path / "api" / "events.json").read_text(encoding="utf-8"))
    parsed_evidence = json.loads((tmp_path / "api" / "evidence_spans.json").read_text(encoding="utf-8"))
    assert parsed_events[0]["claims"][0]["review_status"] == "human_reviewed"
    assert parsed_evidence == []
    assert json.loads((tmp_path / "api" / "fields_summary.json").read_text(encoding="utf-8"))["impact_language"] == 1
    assert api_outputs["events"].endswith("events.json")

    digest = build_generic_digest(
        events=events,
        claims=claims,
        evidence_spans=evidence,
        review_queue=review_queue,
        out_path=tmp_path / "digest.md",
    )
    assert "Human reviewed: 1" in digest
    assert "Rejected: 1" in digest
    assert "weak_claim" not in digest
    assert "affected <operations>" in digest


def test_publishers_work_without_events():
    _, claims, evidence, review_queue = _rows()
    digest = build_generic_digest(events=None, claims=claims, evidence_spans=evidence, review_queue=review_queue)

    assert "Events: 0" in digest
