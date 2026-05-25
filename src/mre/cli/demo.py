from __future__ import annotations

from . import commands as cmd


def register(sub) -> None:
    p = sub.add_parser("demo", help="Run the full offline synthetic demo pipeline.")
    p.add_argument("--root", default=".")
    p.add_argument("--seed", type=int, default=42)
    p.set_defaults(func=cmd.cmd_demo)


    p = sub.add_parser("extraction-demo", help="Run the offline source-document extraction demo.")
    p.add_argument("--root", default=".")
    p.set_defaults(func=cmd.cmd_extraction_demo)

    p = sub.add_parser("source-ingestion-demo", help="Run the offline source-ingestion + extraction demo.")
    p.add_argument("--root", default=".")
    p.set_defaults(func=cmd.cmd_source_ingestion_demo)

    p = sub.add_parser("corpus-demo", help="Run the offline synthetic multi-domain corpus + backtest demo.")
    p.add_argument("--root", default=".")
    p.add_argument("--seed", type=int, default=11)
    p.set_defaults(func=cmd.cmd_corpus_demo)

    p = sub.add_parser("earnings-demo", help="Run the offline synthetic earnings/expectations demo pipeline.")
    p.add_argument("--root", default=".")
    p.add_argument("--seed", type=int, default=7)
    p.set_defaults(func=cmd.cmd_earnings_demo)
