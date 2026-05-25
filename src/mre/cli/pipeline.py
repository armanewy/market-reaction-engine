from __future__ import annotations

from . import commands as cmd


def register(sub) -> None:
    p = sub.add_parser("pipeline-template", help="Create a JSON config for an automated corpus/falsification research run.")
    p.add_argument("--run-id", default="semis_earnings_research_v1")
    p.add_argument("--domain", default="earnings_guidance")
    p.add_argument("--preset", default="semiconductors")
    p.add_argument("--tickers", nargs="*", default=[])
    p.add_argument("--source-mode", default="yfinance_earnings", choices=["manual_events", "yfinance_earnings", "alpha_vantage_earnings", "sec_earnings", "sec_docs", "local_ingestion", "source_documents"])
    p.add_argument("--out", default="research_pipeline.json")
    p.set_defaults(func=cmd.cmd_pipeline_template)

    p = sub.add_parser("run-pipeline", help="Run an automated research loop: source candidates, review queue, corpus, event study, controls, backtests, and gates.")
    p.add_argument("--config", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--stages", nargs="*", default=[], help="Reserved for future partial execution; current implementation runs the full ordered loop.")
    p.set_defaults(func=cmd.cmd_run_pipeline)

    p = sub.add_parser("review-queue", help="Create a human-review queue from candidate events and optional extracted facts.")
    p.add_argument("--events", required=True)
    p.add_argument("--facts", default=None)
    p.add_argument("--out", required=True)
    p.add_argument("--auto-accept-min-confidence", type=float, default=None, help="Prototype only: mark rows reviewed if evidence confidence exceeds this threshold.")
    p.add_argument("--auto-accept-min-facts", type=int, default=1)
    p.set_defaults(func=cmd.cmd_review_queue)

    p = sub.add_parser("pipeline-demo", help="Run the offline automation pipeline demo.")
    p.add_argument("--root", default=".")
    p.add_argument("--seed", type=int, default=1)
    p.set_defaults(func=cmd.cmd_pipeline_demo)
