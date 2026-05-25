from __future__ import annotations

import pytest

from mre.cli import build_parser, main


FIXTURE = "tests/fixtures/cyber_8k/source_documents.csv"


def test_cyber_8k_commands_registered_and_help_loads(capsys):
    parser = build_parser()
    commands = set()
    for action in parser._actions:
        if getattr(action, "choices", None):
            commands.update(action.choices)

    assert {
        "cyber-8k-template",
        "cyber-8k-source-docs",
        "cyber-8k-parse",
        "cyber-8k-review-queue",
        "cyber-8k-build-dataset",
        "cyber-8k-build-site",
        "cyber-8k-digest",
        "cyber-8k-run",
    }.issubset(commands)
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["cyber-8k-parse", "--help"])
    assert exc.value.code == 0
    assert "claims" in capsys.readouterr().out


def test_cyber_8k_parse_cli_runs_on_fixture(tmp_path):
    claims_out = tmp_path / "claims.csv"
    evidence_out = tmp_path / "evidence.csv"

    main(["cyber-8k-parse", "--documents", FIXTURE, "--claims-out", str(claims_out), "--evidence-out", str(evidence_out)])

    assert claims_out.exists()
    assert evidence_out.exists()
