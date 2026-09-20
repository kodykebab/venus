#!/usr/bin/env python3
"""`paracheck review <file>.sol` - full static review of one Solidity file.

Runs every analyzer (parallelism classifier + Slither's detector suite), then
synthesizes a prioritized, plain-English review via Claude when credentials are
available, falling back to deterministic Markdown when they aren't.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "llm"))

from render import render_markdown  # noqa: E402
from review import review_file, review_project  # noqa: E402
from schema import at_least  # noqa: E402


def build_output(report: dict, target: str, use_llm: bool, diff: str | None, source: str | None) -> str:
    if use_llm:
        try:
            from synthesize import render_synthesized, synthesize_review
        except ImportError:
            return render_markdown(report, target)

        synthesized = synthesize_review(report, diff=diff, source=source)
        if synthesized is not None:
            return render_synthesized(synthesized, target)

    return render_markdown(report, target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="a .sol file, or a project directory to review whole")
    parser.add_argument("--solc", default=None, help="explicit solc binary path")
    parser.add_argument("--chain", default=None,
                        help="target chain key or id (monad, ethereum, 10143, ...). "
                             "Parallelism analysis only runs on parallel-execution chains.")
    parser.add_argument("--diff", default=None, help="path to a unified diff for change-scoped review")
    parser.add_argument("--changed-files", default=None,
                        help="comma-separated paths; scopes a project review to a PR's files")
    parser.add_argument("--no-install", action="store_true",
                        help="skip dependency installation in project mode")
    parser.add_argument("--min-severity", default="info", help="drop findings below this severity")
    parser.add_argument("--fail-on", default=None, help="exit 1 if any finding is at or above this severity")
    parser.add_argument("--json", action="store_true", help="emit the raw report as JSON")
    parser.add_argument("--no-llm", action="store_true", help="skip Claude synthesis, render findings directly")
    parser.add_argument("--out", default=None, help="write to this file instead of stdout")
    parser.add_argument("--json-out", default=None, help="also write the raw report JSON here")
    args = parser.parse_args()

    if os.path.isdir(args.target):
        changed = [p.strip() for p in (args.changed_files or "").split(",") if p.strip()]
        report = review_project(
            args.target,
            changed_files=changed or None,
            min_severity=args.min_severity,
            install=not args.no_install,
            chain=args.chain,
        )
    else:
        report = review_file(
            args.target, solc=args.solc, min_severity=args.min_severity, chain=args.chain
        )

    if args.json:
        output = json.dumps(report, indent=2)
    else:
        diff = None
        if args.diff and os.path.exists(args.diff):
            with open(args.diff, encoding="utf-8") as fh:
                diff = fh.read()
        source = None
        if os.path.isfile(args.target):
            with open(args.target, encoding="utf-8") as fh:
                source = fh.read()
        output = build_output(report, args.target, not args.no_llm, diff, source)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(output + "\n")
    else:
        print(output)

    # One analysis run can emit both forms - the GitHub Action needs the Markdown
    # for the PR comment and the JSON for its own output/gating.
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(report, indent=2) + "\n")

    if args.fail_on and not report.get("unanalyzable"):
        blocking = [f for f in report.get("findings", []) if at_least(f["severity"], args.fail_on)]
        if blocking:
            worst = blocking[0]
            print(
                f"::error::{len(blocking)} finding(s) at or above '{args.fail_on}' - "
                f"worst: {worst['check']} ({worst['severity']})",
                file=sys.stderr,
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
