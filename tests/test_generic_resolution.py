from __future__ import annotations

import json

import pytest

from mre.generic.entities import IdentifierHint
from mre.generic.resolution import SimpleHintEntityResolver, SimpleTemporalResolver
from mre.generic.temporal import TemporalHint


def test_simple_hint_resolver_groups_arbitrary_namespaces():
    hints = [
        IdentifierHint(namespace="registry:alpha", value="A-1", label="Alpha", source_doc_id="doc1", confidence=0.7),
        IdentifierHint(namespace="domain:name", value="A-1", label="Alpha Inc", evidence_span_id="span1", confidence=0.8),
    ]
    resolver = SimpleHintEntityResolver()

    result, diagnostics = resolver.resolve(hints, context={"source_doc_id": "doc1"})

    assert diagnostics.hints_total == 2
    assert result.candidates[0].resolution_status == "resolved"
    assert result.candidates[0].confidence > 0.8
    json.dumps(result.to_dict())


def test_simple_hint_resolver_handles_empty_and_ambiguous_hints():
    resolver = SimpleHintEntityResolver()

    empty, empty_diagnostics = resolver.resolve([])
    assert empty.overall_confidence == 0.0
    assert empty_diagnostics.warnings == ["no_hints"]

    result, _ = resolver.resolve(
        [
            IdentifierHint(namespace="text:alias", value="Alpha", confidence=0.5),
            IdentifierHint(namespace="text:alias", value="Beta", confidence=0.5),
        ]
    )
    assert result.candidates[0].resolution_status == "ambiguous"


def test_temporal_resolver_accepts_arbitrary_kinds_and_preferences():
    hints = [
        TemporalHint(kind="observed_window_start", value="2026-01-02", confidence=0.6, basis="body", source_doc_id="doc1"),
        TemporalHint(kind="notice_time", value="2026-01-01", confidence=0.9, basis="header", source_doc_id="doc1"),
        TemporalHint(kind="observed_window_start", value="2026-01-03", confidence=0.3, basis="footer", source_doc_id="doc1"),
    ]
    resolver = SimpleTemporalResolver()

    result, diagnostics = resolver.resolve(hints, preferred_kinds=["notice_time"])

    assert diagnostics.hints_total == 3
    assert result.selected["notice_time"].value == "2026-01-01"
    assert result.selected["observed_window_start"].value == "2026-01-02"
    assert result.overall_confidence == (0.9 + 0.6) / 2
    json.dumps(result.to_dict())


def test_resolution_compatibility_reports_hint_quality():
    entity_report = SimpleHintEntityResolver().compatibility(
        [IdentifierHint(namespace="x", value="A", confidence=0.4), IdentifierHint(namespace="y", value="A", confidence=0.8)]
    )
    temporal_report = SimpleTemporalResolver().compatibility([TemporalHint(kind="custom", value="now", confidence=0.7, basis="text")])

    assert entity_report.dimensions[0].score == pytest.approx(0.6)
    assert temporal_report.dimensions[0].name == "temporal_resolution_confidence"
