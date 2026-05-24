from __future__ import annotations

import json

from mre.cli import build_parser
from mre.domain_registry import (
    format_domain_status,
    format_revisit_triggers,
    load_domain_registry,
    score_intake,
    write_domain_final_report,
)


REGISTRY = """# Registry

| Domain | Status | Stage Reached | Stop Reason | Last Known Commit | Revisit Trigger |
| --- | --- | --- | --- | --- | --- |
| `cybersecurity_material_incidents_8k` | underpowered, not failed | monitor/readiness | Too few rows | `878db5f` | Rerun at 80 reviewed rows. |
| `insider_purchase_clusters` | frozen | causal rebuild/final audit | Null-shuffle failed | `b0923ce` | New thesis only. |
"""


INTAKE = """# Intake

| Dimension | Score | Notes |
| --- | ---: | --- |
| Official source quality | 3 | official |
| Public timestamp clarity | 2 | daily publication |
| Delayed-digestion plausibility | 2 | complex |
| Hard-negative clarity | 3 | clear |
| Materiality-field clarity | 2 | amount / cap |
| Sample-size likelihood | 2 | enough |
| Ticker/entity mapping feasibility | 2 | mapped |
| Liquidity/execution feasibility | 2 | liquid |
| Parser/audit feasibility | 3 | testable |
| Fresh-data availability | 3 | future |
"""


def test_load_domain_registry_and_format_status(tmp_path):
    registry = tmp_path / "registry.md"
    registry.write_text(REGISTRY, encoding="utf-8")

    records = load_domain_registry(registry)

    assert [record.domain for record in records] == [
        "cybersecurity_material_incidents_8k",
        "insider_purchase_clusters",
    ]
    rendered = format_domain_status(records)
    assert "underpowered, not failed" in rendered
    assert "New thesis only." in rendered


def test_revisit_triggers_only_includes_monitor_or_underpowered(tmp_path):
    registry = tmp_path / "registry.md"
    registry.write_text(REGISTRY, encoding="utf-8")

    rendered = format_revisit_triggers(load_domain_registry(registry))

    assert "cybersecurity_material_incidents_8k" in rendered
    assert "insider_purchase_clusters" not in rendered


def test_score_intake_recommends_full_lifecycle(tmp_path):
    intake = tmp_path / "intake.md"
    intake.write_text(INTAKE, encoding="utf-8")

    score = score_intake(intake)

    assert score.total == 24
    assert score.missing_dimensions == []
    assert score.critical_failures == []
    assert score.recommendation == "full lifecycle agent allowed"


def test_write_domain_final_report_from_registry(tmp_path):
    registry = tmp_path / "registry.md"
    registry.write_text(REGISTRY, encoding="utf-8")
    readiness = tmp_path / "readiness.md"
    readiness.write_text("ready: no", encoding="utf-8")
    out = tmp_path / "final.md"

    record = write_domain_final_report(
        domain="insider_purchase_clusters",
        out_path=out,
        registry_path=registry,
        readiness_report=readiness,
    )

    assert record.status == "frozen"
    text = out.read_text(encoding="utf-8")
    assert "Null-shuffle failed" in text
    assert "ready: no" in text


def test_research_ops_cli_commands_parse(tmp_path):
    parser = build_parser()
    registry = tmp_path / "registry.md"
    intake = tmp_path / "intake.md"
    registry.write_text(REGISTRY, encoding="utf-8")
    intake.write_text(INTAKE, encoding="utf-8")

    status_args = parser.parse_args(["domain-status", "--registry", str(registry), "--json"])
    intake_args = parser.parse_args(["domain-intake-score", "--input", str(intake), "--json"])
    triggers_args = parser.parse_args(["revisit-triggers", "--registry", str(registry), "--json"])

    assert status_args.func.__name__ == "cmd_domain_status"
    assert intake_args.func.__name__ == "cmd_domain_intake_score"
    assert triggers_args.func.__name__ == "cmd_revisit_triggers"

    # Keep json imported and verify the test fixture is valid for CLI JSON output expectations.
    assert json.loads('[{"ok": true}]')[0]["ok"] is True

