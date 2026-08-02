"""Explorer CLI (Step 14 — collection must actually execute, not be manual).

    poetry run explorer collect-brasileirao [--seasons 2020,2021] [--no-ai]
    poetry run explorer collect --competition la_liga --season 2023
    poetry run explorer serve   # Console read API (needs --with api)
"""

from __future__ import annotations

import argparse
import json
import sys

from explorer.adapters.espn import ESPNAdapter
from explorer.jobs.brasileirao import BRASILEIRAO_SEASONS, run_brasileirao
from explorer.jobs.runner import JobRunner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="explorer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("collect-brasileirao", help="Collect Brasileirão 2020–2024")
    b.add_argument("--seasons", default=",".join(BRASILEIRAO_SEASONS))
    b.add_argument("--no-ai", action="store_true", help="disable the AI layer for this run")

    c = sub.add_parser("collect", help="Collect one competition/season via ESPN")
    c.add_argument("--competition", required=True)
    c.add_argument("--season", required=True)
    c.add_argument("--no-ai", action="store_true")

    sub.add_parser("serve", help="Run the Console read API")

    args = parser.parse_args(argv)

    if args.cmd == "collect-brasileirao":
        runner = JobRunner(use_ai=not args.no_ai)
        recs = run_brasileirao(runner, tuple(s.strip() for s in args.seasons.split(",")))
        _print_summary(recs)
        return 0
    if args.cmd == "collect":
        runner = JobRunner(use_ai=not args.no_ai)
        rec = runner.run(ESPNAdapter(), args.competition, args.season)
        runner.tickets.flush()
        _print_summary([rec])
        return 0
    if args.cmd == "serve":
        import uvicorn  # type: ignore

        from explorer.api.app import create_app

        uvicorn.run(create_app(), host="0.0.0.0", port=8090)
        return 0
    return 1


def _print_summary(records: list) -> None:
    from dataclasses import asdict

    summary = [asdict(r) for r in records]
    totals = {
        "validated": sum(r["records_validated"] for r in summary),
        "rejected": sum(r["records_rejected"] for r in summary),
        "review": sum(r["records_review"] for r in summary),
        "collected": sum(r["records_collected"] for r in summary),
    }
    json.dump({"jobs": summary, "totals": totals}, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
