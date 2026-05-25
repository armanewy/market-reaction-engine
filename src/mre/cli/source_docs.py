from __future__ import annotations

from . import commands as cmd


def register(sub) -> None:
    p = sub.add_parser("source-docs-template", help="Create a raw source-document manifest template for extraction.")
    p.add_argument("--out", default="data/events/source_documents.csv")
    p.set_defaults(func=cmd.cmd_source_docs_template)

    p = sub.add_parser("ingestion-template", help="Create a URL/local/inline source-ingestion template.")
    p.add_argument("--out", default="data/events/source_ingestion_template.csv")
    p.set_defaults(func=cmd.cmd_ingestion_template)

    p = sub.add_parser("ingest-source-docs", help="Download/normalize URL, local-path, or inline source rows into extraction-ready text files.")
    p.add_argument("--input", required=True, help="Input CSV with source_url, path, or text plus ticker/event_time metadata.")
    p.add_argument("--out", required=True, help="Output source-document manifest compatible with extract-facts.")
    p.add_argument("--docs-dir", required=True, help="Directory for normalized text files.")
    p.add_argument("--user-agent", default=None)
    p.add_argument("--requests-per-second", type=float, default=2.0)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--include-inline-text", action="store_true", help="Also include normalized text in the output CSV; usually leave off for large docs.")
    p.add_argument("--min-text-chars", type=int, default=20)
    p.set_defaults(func=cmd.cmd_ingest_source_docs)

    p = sub.add_parser("sec-source-docs", help="Download SEC filing primary docs and likely earnings-release exhibits into a source-document manifest.")
    p.add_argument("--preset", help="Preset, e.g. semiconductors, mega_cap_tech, software.")
    p.add_argument("--tickers", nargs="*", default=[])
    p.add_argument("--benchmark", default="")
    p.add_argument("--sector-benchmark", default="")
    p.add_argument("--forms", default="8-K", help="Comma-separated SEC forms, default 8-K.")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--item-filter", default="2.02", help="Comma-separated 8-K item filter. Use 'all' to disable.")
    p.add_argument("--limit-per-ticker", type=int, default=None)
    p.add_argument("--no-primary", action="store_true", help="Do not include primary filing document.")
    p.add_argument("--no-exhibits", action="store_true", help="Do not include likely earnings-release exhibits.")
    p.add_argument("--exhibit-pattern", default=r"(?i)(ex[-_]?99|exhibit[-_ ]?99|dex99|99[._-]?1|earnings|results|press[-_ ]?release)")
    p.add_argument("--docs-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--user-agent", default=None)
    p.add_argument("--requests-per-second", type=float, default=5.0)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--min-text-chars", type=int, default=40)
    p.set_defaults(func=cmd.cmd_sec_source_docs)
