from __future__ import annotations

import argparse

from . import core, corpus, cyber_8k, demo, domain_registry, domains, earnings, expectations, extraction, generic, pipeline, sec, source_docs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mre",
        description="Market Reaction Engine: event-study workbench for abnormal market reactions.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    pipeline.register(sub)
    generic.register(sub)
    corpus.register(sub)
    earnings.register(sub)
    source_docs.register(sub)
    cyber_8k.register(sub)
    sec.register_domain_commands(sub)
    domain_registry.register(sub)
    extraction.register(sub)
    domains.register(sub)
    expectations.register(sub)
    core.register(sub)
    sec.register_template_command(sub)
    demo.register(sub)

    return parser
