from __future__ import annotations

from . import commands as cmd


def register(sub) -> None:
    p = sub.add_parser("enrich-expectations", help="Add pre-event price/expectation context features to an event CSV.")
    p.add_argument("--events", required=True)
    p.add_argument("--prices-dir", required=True)
    p.add_argument("--benchmark", default="SPY")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd.cmd_enrich_expectations)

    p = sub.add_parser("merge-expectations", help="Merge external point-in-time expectation fields into an event CSV.")
    p.add_argument("--events", required=True)
    p.add_argument("--expectations", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--fill-labels", action="store_true")
    p.set_defaults(func=cmd.cmd_merge_expectations)

    p = sub.add_parser("release-times-template", help="Create a template for exact release timestamps.")
    p.add_argument("--events", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd.cmd_release_times_template)

    p = sub.add_parser("merge-release-times", help="Merge exact release timestamps into events and update release_session.")
    p.add_argument("--events", required=True)
    p.add_argument("--release-times", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--key", default="event_id")
    p.add_argument("--require-all-events", action="store_true")
    p.set_defaults(func=cmd.cmd_merge_release_times)

    p = sub.add_parser("options-template", help="Create an option snapshot template for ATM-straddle implied moves.")
    p.add_argument("--events", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd.cmd_options_template)

    p = sub.add_parser("merge-options", help="Estimate and merge pre-event implied move from option snapshot rows.")
    p.add_argument("--events", required=True)
    p.add_argument("--options", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--max-quote-age-days", type=int, default=14, help="Use -1 to disable quote-age filtering.")
    p.set_defaults(func=cmd.cmd_merge_options)

    p = sub.add_parser("analyst-revisions-template", help="Create a template for point-in-time analyst estimate revisions.")
    p.add_argument("--events", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd.cmd_analyst_revisions_template)

    p = sub.add_parser("merge-analyst-revisions", help="Compute and merge analyst revision features into events.")
    p.add_argument("--events", required=True)
    p.add_argument("--revisions", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--windows", default="7,30")
    p.add_argument("--metrics", default="eps,revenue,gross_margin,forward_revenue")
    p.set_defaults(func=cmd.cmd_merge_analyst_revisions)
