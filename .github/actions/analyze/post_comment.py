#!/usr/bin/env python3
"""Posts the rendered ParaCheck review to the pull request and applies the
configured gates.

Rendering (and Claude synthesis) already happened in review_cli.py - this step
only delivers the result and decides the job's exit code, so there's one place
that owns exit-code policy. Stdlib only; no dependencies beyond the analyzer's.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

SEVERITIES = ["critical", "high", "medium", "low", "info", "optimization"]


def severity_at_least(severity: str, minimum: str) -> bool:
    def rank(s: str) -> int:
        return SEVERITIES.index(s) if s in SEVERITIES else len(SEVERITIES)
    return rank(severity) <= rank(minimum)


def post_pr_comment(body: str) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr_number = os.environ.get("PR_NUMBER")
    if not (token and repo and pr_number):
        print("Not a pull_request run (or no token) - skipping PR comment.")
        return

    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments",
        data=json.dumps({"body": body}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            print(f"Posted PR comment (status {response.status}).")
    except urllib.error.HTTPError as exc:
        # A fork PR's read-only token can't comment. That must not fail the job -
        # the review is in the job log and in the action's report-json output.
        print(f"Failed to post PR comment: {exc.code} {exc.read().decode('utf-8', 'replace')}")


def main() -> None:
    with open(os.environ["REVIEW_MARKDOWN_FILE"], encoding="utf-8") as fh:
        review_markdown = fh.read()
    with open(os.environ["REPORT_JSON_FILE"], encoding="utf-8") as fh:
        report = json.load(fh)

    if os.environ.get("COMMENT_ON_PR", "true").lower() == "true":
        post_pr_comment(review_markdown)

    if report.get("unanalyzable"):
        print(f"::warning::ParaCheck could not analyze this file: {report.get('reason', '')}")
        return

    failures = []

    fail_on = (os.environ.get("FAIL_ON") or "").strip()
    if fail_on:
        blocking = [f for f in report.get("findings", []) if severity_at_least(f["severity"], fail_on)]
        if blocking:
            worst = blocking[0]
            failures.append(
                f"{len(blocking)} finding(s) at or above '{fail_on}' "
                f"- worst: {worst['check']} ({worst['severity']})"
            )

    fail_below = (os.environ.get("FAIL_BELOW_SCORE") or "").strip()
    if fail_below:
        scores = [
            c["parallelismScore"]
            for c in report.get("contracts", [])
            if not c.get("unanalyzable") and c.get("parallelismScore") is not None
        ]
        if scores and min(scores) < int(fail_below):
            failures.append(f"lowest parallelism score {min(scores)} is below threshold {fail_below}")

    for failure in failures:
        print(f"::error::{failure}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
