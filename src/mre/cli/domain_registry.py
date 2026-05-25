from __future__ import annotations

from . import commands as cmd


def register(sub) -> None:
    p = sub.add_parser("domain-status", help="Summarize domain registry status and revisit triggers.")
    p.add_argument("--registry", default=str(cmd.DEFAULT_REGISTRY_PATH))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd.cmd_domain_status)

    p = sub.add_parser("domain-intake-score", help="Score a proposed domain intake Markdown file.")
    p.add_argument("--input", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd.cmd_domain_intake_score)

    p = sub.add_parser("revisit-triggers", help="List monitor or underpowered domains and their revisit triggers.")
    p.add_argument("--registry", default=str(cmd.DEFAULT_REGISTRY_PATH))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd.cmd_revisit_triggers)

    p = sub.add_parser("domain-final-report", help="Generate a final report from the domain registry and supporting reports.")
    p.add_argument("--domain", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--registry", default=str(cmd.DEFAULT_REGISTRY_PATH))
    p.add_argument("--readiness-report")
    p.add_argument("--parser-audit")
    p.add_argument("--timestamp-audit")
    p.add_argument("--falsification-report")
    p.add_argument("--fresh-confirmation-report")
    p.add_argument("--execution-audit")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=cmd.cmd_domain_final_report)
