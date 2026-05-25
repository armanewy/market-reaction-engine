from __future__ import annotations

import argparse

from mre.cli import build_parser


def _subcommand_names(parser: argparse.ArgumentParser) -> set[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("Expected CLI parser to define subcommands")


def test_cli_parser_registers_representative_command_groups():
    parser = build_parser()
    commands = _subcommand_names(parser)

    assert {
        "run-pipeline",
        "build-corpus",
        "sec-domain-source-docs",
        "extract-facts",
        "parse-biotech-catalysts",
        "merge-expectations",
        "run-event-study",
        "research-backtest",
        "sec-template",
        "demo",
    }.issubset(commands)


def test_cli_parser_preserves_representative_handlers():
    parser = build_parser()

    assert parser.parse_args(["run-pipeline", "--config", "pipeline.json"]).func.__name__ == "cmd_run_pipeline"
    assert (
        parser.parse_args(["run-event-study", "--events", "events.csv", "--prices-dir", "prices"]).func.__name__
        == "cmd_run_event_study"
    )
    assert parser.parse_args(["sec-template", "--ticker", "ABC", "--out", "events.csv"]).func.__name__ == "cmd_sec_template"
