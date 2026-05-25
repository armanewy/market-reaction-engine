from __future__ import annotations

import json

import pytest

from mre.cli.main import main
from mre.cli.parser import build_parser


def test_generic_commands_registered_and_help_loads(capsys):
    parser = build_parser()
    commands = set()
    for action in parser._actions:
        if getattr(action, "choices", None):
            commands.update(action.choices)

    expected = {
        "generic-template",
        "generic-run",
        "generic-review-queue",
        "generic-missing-claim-template",
        "generic-missing-claim-report",
        "generic-quality-report",
        "generic-build-site",
        "generic-api-export",
        "generic-digest",
    }
    assert expected.issubset(commands)
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["generic-run", "--help"])
    assert exc.value.code == 0
    assert "generic-run" in capsys.readouterr().out.lower()


def test_generic_run_cli_runs_toy_pipeline(tmp_path, capsys):
    config = tmp_path / "generic_pipeline.json"
    out_dir = tmp_path / "out"
    main(["generic-template", "--out", str(config), "--out-dir", str(out_dir)])
    main(["generic-run", "--config", str(config)])

    captured = capsys.readouterr().out
    assert "generic evidence pipeline template" in captured
    assert (out_dir / "pipeline_report.json").exists()
    report = json.loads((out_dir / "pipeline_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "ok"


def test_generic_missing_claim_cli_template_and_report(tmp_path, capsys):
    events = tmp_path / "events.csv"
    claims = tmp_path / "claims.csv"
    audit = tmp_path / "missing_claims.csv"
    report_json = tmp_path / "missing_claim_report.json"
    events.write_text("event_id,event_candidate_id,source_doc_id\ne1,ec1,doc1\n", encoding="utf-8")
    claims.write_text("claim_id,field_name,review_status\nc1,field,human_reviewed\n", encoding="utf-8")

    main(
        [
            "generic-missing-claim-template",
            "--events",
            str(events),
            "--expected-fields",
            "field",
            "--out",
            str(audit),
        ]
    )
    main(
        [
            "generic-missing-claim-report",
            "--claims",
            str(claims),
            "--audit",
            str(audit),
            "--out-json",
            str(report_json),
        ]
    )

    assert audit.exists()
    assert report_json.exists()
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["overall_estimated_recall"] == 0.5
    assert "generic missing-claim audit" in capsys.readouterr().out
