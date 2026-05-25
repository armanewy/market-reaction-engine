from __future__ import annotations

from . import commands as cmd


def register(sub) -> None:
    p = sub.add_parser("generic-template", help="Write a generic evidence pipeline config template.")
    p.add_argument("--out", default="generic_pipeline.json")
    p.add_argument("--out-dir", default="artifacts/generic_toy")
    p.add_argument("--adapter", choices=["toy_official", "toy_weak"], default="toy_official")
    p.add_argument("--auto-accept-min-confidence", type=float, default=0.8)
    p.set_defaults(func=cmd.cmd_generic_template)

    p = sub.add_parser("generic-run", help="Run the generic toy evidence pipeline.")
    p.add_argument("--config", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd.cmd_generic_run)

    p = sub.add_parser("generic-review-queue", help="Build a generic claim/evidence review queue.")
    p.add_argument("--claims", required=True)
    p.add_argument("--evidence-spans", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--auto-accept-min-confidence", type=float, default=None)
    p.add_argument("--allow-missing-evidence", action="store_true")
    p.set_defaults(func=cmd.cmd_generic_review_queue)

    p = sub.add_parser("generic-quality-report", help="Build a generic evidence dataset quality report.")
    p.add_argument("--claims", required=True)
    p.add_argument("--evidence-spans", required=True)
    p.add_argument("--events")
    p.add_argument("--review-queue")
    p.add_argument("--out-json")
    p.add_argument("--out-md")
    p.set_defaults(func=cmd.cmd_generic_quality_report)

    p = sub.add_parser("generic-build-site", help="Build a static generic evidence dataset site.")
    p.add_argument("--claims", required=True)
    p.add_argument("--evidence-spans", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--events")
    p.add_argument("--review-queue")
    p.add_argument("--title", default="Evidence Event Dataset")
    p.set_defaults(func=cmd.cmd_generic_build_site)

    p = sub.add_parser("generic-api-export", help="Build generic evidence dataset JSON files.")
    p.add_argument("--claims", required=True)
    p.add_argument("--evidence-spans", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--events")
    p.add_argument("--review-queue")
    p.add_argument("--omit-evidence", action="store_true")
    p.set_defaults(func=cmd.cmd_generic_api_export)

    p = sub.add_parser("generic-digest", help="Build a generic evidence dataset Markdown digest.")
    p.add_argument("--claims", required=True)
    p.add_argument("--evidence-spans", required=True)
    p.add_argument("--events")
    p.add_argument("--review-queue")
    p.add_argument("--out")
    p.add_argument("--title", default="Evidence Event Digest")
    p.set_defaults(func=cmd.cmd_generic_digest)
