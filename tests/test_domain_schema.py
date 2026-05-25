from __future__ import annotations

import json

from mre.domain_schema import DEFAULT_PROMOTION_GATES, domain_schema_from_mapping, load_domain_schema, load_domain_schemas


def test_pilot_domain_schema_loads():
    schema = load_domain_schema("schemas/domains/cybersecurity_material_incidents_8k.json")

    assert schema.domain == "cybersecurity_material_incidents_8k"
    assert schema.event_type == "cybersecurity"
    assert "release_session" in schema.required_review_columns
    assert schema.promotion_gates["min_reviewed_rows"] == 80


def test_schema_loader_reads_directory():
    schemas = load_domain_schemas("schemas/domains")

    assert {"cybersecurity_material_incidents_8k", "earnings_guidance"}.issubset(schemas)


def test_missing_required_fields_are_rejected():
    try:
        domain_schema_from_mapping({"domain": "x", "event_type": "event"})
    except ValueError as exc:
        assert "missing required fields" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_duplicate_columns_are_rejected():
    data = {
        "domain": "x",
        "event_type": "event",
        "default_subtype": "candidate",
        "description": "test",
        "required_review_columns": ["event_time", "event_time"],
    }

    try:
        domain_schema_from_mapping(data)
    except ValueError as exc:
        assert "duplicate values" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_promotion_gate_defaults_applied(tmp_path):
    path = tmp_path / "schema.json"
    path.write_text(
        json.dumps(
            {
                "domain": "minimal_domain",
                "event_type": "event",
                "default_subtype": "candidate",
                "description": "Minimal schema.",
            }
        ),
        encoding="utf-8",
    )

    schema = load_domain_schema(path)

    assert schema.promotion_gates == DEFAULT_PROMOTION_GATES
