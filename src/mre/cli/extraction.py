from __future__ import annotations

import argparse

from . import commands as cmd


def register(sub) -> None:
    p = sub.add_parser("extract-facts", help="Extract evidence-grounded earnings/guidance facts from a source-document manifest.")
    p.add_argument("--documents", required=True, help="CSV manifest with source_doc_id, ticker, event_time, and text/path.")
    p.add_argument("--facts-out", required=True, help="Output extracted fact rows with evidence spans.")
    p.add_argument("--expectations-out", required=True, help="Output pivoted expectation-feature rows.")
    p.add_argument("--events-out", required=True, help="Output event rows generated from source documents.")
    p.set_defaults(func=cmd.cmd_extract_facts)

    p = sub.add_parser("extraction-packets", help="Create JSONL work packets for an external LLM extractor; does not call an LLM.")
    p.add_argument("--documents", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--max-chars", type=int, default=12000)
    p.set_defaults(func=cmd.cmd_extraction_packets)

    p = sub.add_parser("validate-llm-facts", help="Validate JSONL LLM extraction output against source-document evidence.")
    p.add_argument("--documents", required=True)
    p.add_argument("--llm-jsonl", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--allow-missing-evidence", action="store_true")
    p.set_defaults(func=cmd.cmd_validate_llm_facts)

    p = sub.add_parser("parse-exhibit99", help="Parse semiconductor Exhibit 99 earnings releases with table/sentence-aware rules.")
    p.add_argument("--documents", required=True, help="Source-document manifest with Exhibit 99 text paths.")
    p.add_argument("--facts-out", required=True)
    p.add_argument("--features-out", required=True)
    p.add_argument("--min-confidence", type=float, default=0.0)
    p.add_argument("--usable-confidence", type=float, default=0.80)
    p.set_defaults(func=cmd.cmd_parse_exhibit99)

    p = sub.add_parser("validate-exhibit99-parser", help="Validate Exhibit 99 parser facts against a gold-set CSV.")
    p.add_argument("--facts", required=True)
    p.add_argument("--gold", required=True)
    p.add_argument("--errors-out", required=True)
    p.add_argument("--report-out", required=True)
    p.set_defaults(func=cmd.cmd_validate_exhibit99_parser)

    def add_management_guidance_bridge_parser(name: str) -> argparse.ArgumentParser:
        parser = sub.add_parser(name, help="Build actual-vs-prior-management-guidance surprise rows from parsed Exhibit 99 features.")
        parser.add_argument("--features", required=True, help="Parsed Exhibit 99 feature CSV.")
        parser.add_argument("--events", default=None, help="Optional reviewed event CSV for release_session/source metadata.")
        parser.add_argument("--out", required=True)
        parser.add_argument("--failures-out", default=None)
        parser.add_argument("--report-out", default=None)
        parser.add_argument("--period-audit-out", default=None)
        parser.add_argument("--expansion-report-out", default=None)
        parser.add_argument("--event-study", default=None, help="Optional event-study CSV for descriptive diagnostics only.")
        parser.add_argument("--min-confidence", type=float, default=0.80)
        parser.add_argument("--min-prior-event-gap-days", type=int, default=45)
        parser.add_argument("--max-prior-event-gap-days", type=int, default=190)
        parser.add_argument("--min-actual-to-prior-ratio", type=float, default=0.50)
        parser.add_argument("--max-actual-to-prior-ratio", type=float, default=1.75)
        parser.add_argument("--no-require-period-alignment", action="store_true")
        parser.set_defaults(func=cmd.cmd_management_guidance_bridge)
        return parser

    add_management_guidance_bridge_parser("build-management-guidance-bridge")
    add_management_guidance_bridge_parser("management-guidance-bridge")

    p = sub.add_parser("validate-management-guidance-bridge", help="Validate management-guidance bridge quality gates.")
    p.add_argument("--bridge", required=True)
    p.add_argument("--report-out", required=True)
    p.add_argument("--min-ready-rows", type=int, default=50)
    p.add_argument("--preferred-ready-rows", type=int, default=80)
    p.add_argument("--min-tickers", type=int, default=6)
    p.add_argument("--max-single-ticker-share", type=float, default=0.35)
    p.add_argument("--min-prior-event-gap-days", type=int, default=45)
    p.add_argument("--max-prior-event-gap-days", type=int, default=190)
    p.add_argument("--min-confidence", type=float, default=0.80)
    p.set_defaults(func=cmd.cmd_validate_management_guidance_bridge)
