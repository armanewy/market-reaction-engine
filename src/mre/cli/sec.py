from __future__ import annotations

from . import commands as cmd


def register_domain_commands(sub) -> None:
    p = sub.add_parser("sec-domain-source-docs", help="Build a shared SEC source manifest for SEC-native domains.")
    p.add_argument("--domain", required=True)
    ticker_group = p.add_mutually_exclusive_group(required=True)
    ticker_group.add_argument("--tickers")
    ticker_group.add_argument("--ticker-csv")
    p.add_argument("--forms", required=True)
    p.add_argument("--items")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--docs-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--sec-user-agent", default="MarketReactionEngine/0.8 sec-core-infrastructure")
    p.set_defaults(func=cmd.cmd_sec_domain_source_docs)

    p = sub.add_parser("sec-domain-review-template", help="Create a review template from a SEC source or event file.")
    p.add_argument("--input", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd.cmd_sec_domain_review_template)

    p = sub.add_parser("sec-domain-context", help="Add common SEC-domain price and capitalization context.")
    p.add_argument("--input", required=True)
    p.add_argument("--prices-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--benchmark-ticker", default="SPY")
    p.add_argument("--shares-outstanding")
    p.add_argument("--market-cap")
    p.set_defaults(func=cmd.cmd_sec_domain_context)

    p = sub.add_parser("sec-domain-timestamp-audit", help="Audit SEC event timestamps and first tradable windows.")
    p.add_argument("--input", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--has-intraday-prices", action="store_true")
    p.set_defaults(func=cmd.cmd_sec_domain_timestamp_audit)

    p = sub.add_parser("sec-domain-readiness-report", help="Create a common readiness report for a SEC-native domain.")
    p.add_argument("--domain", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--sources")
    p.add_argument("--parsed")
    p.add_argument("--review")
    p.add_argument("--parser-audit")
    p.add_argument("--timestamp-audit")
    p.add_argument("--context")
    p.add_argument("--min-train", type=int, default=40)
    p.set_defaults(func=cmd.cmd_sec_domain_readiness_report)


def register_template_command(sub) -> None:
    p = sub.add_parser("sec-template", help="Create an event template from recent SEC submissions.")
    p.add_argument("--ticker", required=True)
    p.add_argument("--forms", default="8-K,10-Q,10-K")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--out", required=True)
    p.add_argument("--user-agent", default=None)
    p.add_argument("--requests-per-second", type=float, default=5.0)
    p.set_defaults(func=cmd.cmd_sec_template)
