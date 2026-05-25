from __future__ import annotations

from . import commands as cmd


def register(sub) -> None:
    p = sub.add_parser("corpus-domains", help="List supported narrow-domain corpus schemas.")
    p.set_defaults(func=cmd.cmd_corpus_domains)

    p = sub.add_parser("domain-template", help="Create a domain-specific curated event template.")
    p.add_argument("--domain", required=True, help="earnings_guidance, fda_biotech, biotech_fda_clinical_catalyst, regulatory_legal, cyber_incident, recall_safety, or capital_raise_dilution")
    p.add_argument("--tickers", nargs="*", default=[])
    p.add_argument("--corpus-name", default=None)
    p.add_argument("--rows-per-ticker", type=int, default=1)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd.cmd_domain_template)

    p = sub.add_parser("build-corpus", help="Merge and validate curated event CSVs into one narrow-domain corpus.")
    p.add_argument("--inputs", nargs="+", required=True)
    p.add_argument("--domain", default=None)
    p.add_argument("--corpus-name", default=None)
    p.add_argument("--require-reviewed", action="store_true", help="Keep only rows that pass corpus validation.")
    p.add_argument("--min-materiality", type=float, default=0.0)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd.cmd_build_corpus)

    p = sub.add_parser("validate-corpus", help="Validate a narrow-domain event corpus for missing review/evidence fields.")
    p.add_argument("--events", required=True)
    p.add_argument("--domain", default=None)
    p.add_argument("--min-materiality", type=float, default=0.0)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd.cmd_validate_corpus)

    p = sub.add_parser("base-rates", help="Summarize abnormal-return base rates by event metadata bins.")
    p.add_argument("--event-study", required=True)
    p.add_argument("--horizon", type=int, default=1)
    p.add_argument("--group-by", default="event_family,event_subtype,surprise_direction,surprise_magnitude")
    p.add_argument("--min-count", type=int, default=3)
    p.add_argument("--head", type=int, default=20)
    p.add_argument("--out")
    p.set_defaults(func=cmd.cmd_base_rates)
