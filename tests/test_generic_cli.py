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
