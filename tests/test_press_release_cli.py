from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from mre.cli.main import main
from mre.cli.parser import build_parser


FIXTURE = Path("tests/fixtures/company_press_releases/source_documents.csv")


def test_press_release_commands_registered_and_help_loads(capsys):
    parser = build_parser()
    commands = set()
    for action in parser._actions:
        if getattr(action, "choices", None):
            commands.update(action.choices)

    assert {"press-release-template", "press-release-run"}.issubset(commands)
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["press-release-run", "--help"])
    assert exc.value.code == 0
    assert "press-release-run" in capsys.readouterr().out


def test_press_release_template_cli_writes_manifest(tmp_path, capsys):
    out = tmp_path / "source_documents.csv"
    main(["press-release-template", "--out", str(out)])

    captured = capsys.readouterr().out
    frame = pd.read_csv(out)
    assert "official-company press-release manifest template" in captured
    assert list(frame.columns) == [
        "source_record_id",
        "source_url",
        "title",
        "published_at",
        "retrieved_at",
        "document_type",
        "document_subtype",
        "source_authority_level",
        "source_role",
        "jurisdiction",
        "company_name",
        "domain",
        "path",
        "text",
    ]


def test_press_release_run_cli_runs_offline_fixture(tmp_path, capsys):
    out_dir = tmp_path / "press_release"
    main(["press-release-run", "--documents", str(FIXTURE), "--out-dir", str(out_dir)])

    captured = capsys.readouterr().out
    report = json.loads(captured)
    assert report["status"] == "ok"
    assert (out_dir / "pipeline_report.json").exists()
    assert (out_dir / "press_release_claim_review_queue.csv").exists()
    assert (out_dir / "press_release_quality_report.json").exists()
    assert (out_dir / "site" / "index.html").exists()
    assert (out_dir / "api" / "events.json").exists()
