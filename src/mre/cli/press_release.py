from __future__ import annotations

from . import commands as cmd


def register(sub) -> None:
    p = sub.add_parser("press-release-template", help="Write an official-company press-release manifest template.")
    p.add_argument("--out", default="company_press_releases.csv")
    p.set_defaults(func=cmd.cmd_press_release_template)

    p = sub.add_parser("press-release-run", help="Run the offline official-company press-release experiment.")
    p.add_argument("--documents", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--auto-accept-min-confidence", type=float, default=0.8)
    p.add_argument("--no-quality-report", action="store_true")
    p.add_argument("--no-static-site", action="store_true")
    p.add_argument("--no-api-export", action="store_true")
    p.add_argument("--no-digest", action="store_true")
    p.add_argument("--no-run-manifest", action="store_true")
    p.set_defaults(func=cmd.cmd_press_release_run)
