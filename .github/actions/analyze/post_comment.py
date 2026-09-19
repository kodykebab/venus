#!/usr/bin/env python3
"""Formats the ParaCheck static-analysis report as a PR comment, posts it via the
GitHub REST API (stdlib only - no extra dependencies for this lightweight action), and
exits non-zero if any contract's score is below --fail-below-score.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def format_comment(report: dict, contract_path: str) -> str:
    lines = [f"### ParaCheck static analysis — `{contract_path}`", ""]

    if report.get("unanalyzable"):
        lines.append(f"⚠️ **Unanalyzable**: {report.get('reason', 'unknown reason')}")
        return "\n".join(lines)

    for contract in report.get("contracts", []):
        if contract.get("unanalyzable"):
            lines.append(f"**{contract['contract']}** — ⚠️ unanalyzable: {contract.get('reason', '')}")
            continue

        score = contract["parallelismScore"]
        badge = "🟢" if score >= 70 else "🟡" if score >= 30 else "🔴"
        lines.append(f"**{contract['contract']}** — {badge} parallelism score **{score}**/100")

        safe = contract.get("safeFunctions") or []
        if safe:
            lines.append(f"- Safe: {', '.join(f'`{fn}()`' for fn in safe)}")

        flags = contract.get("flags") or []
        if flags:
            for flag in flags:
                touched = ", ".join(flag["touchedBy"])
                lines.append(f"- 🔴 `{flag['slot']}` (touched by {touched}): {flag['suggestedFix']}")
        else:
            lines.append("- No hot slots flagged.")
        lines.append("")

    lines.append("_Posted by [ParaCheck](https://github.com/kodykebab/venus)'s analyze GitHub Action._")
    return "\n".join(lines)


def post_pr_comment(body: str) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr_number = os.environ.get("PR_NUMBER")
    if not (token and repo and pr_number):
        print("Not a pull_request run (or no token) - skipping PR comment.")
        return

    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    payload = json.dumps({"body": body}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"Posted PR comment (status {resp.status}).")
    except urllib.error.HTTPError as exc:
        # Never let a comment-posting failure (e.g. a fork PR's read-only token) fail the
        # job by itself - the analysis result (printed to the job log either way, and
        # returned via the action's own report-json output) is what actually matters.
        print(f"Failed to post PR comment: {exc.code} {exc.read().decode('utf-8', 'replace')}")


def main() -> None:
    report = json.loads(os.environ["REPORT_JSON"])
    contract_path = os.environ.get("CONTRACT_PATH", "")
    comment_on_pr = os.environ.get("COMMENT_ON_PR", "true").lower() == "true"
    fail_below = os.environ.get("FAIL_BELOW_SCORE", "").strip()

    body = format_comment(report, contract_path)
    print(body)

    if comment_on_pr:
        post_pr_comment(body)

    if not fail_below:
        return

    threshold = int(fail_below)
    scores = [
        c["parallelismScore"]
        for c in report.get("contracts", [])
        if not c.get("unanalyzable")
    ]
    if scores and min(scores) < threshold:
        print(f"::error::Lowest parallelism score {min(scores)} is below threshold {threshold}")
        sys.exit(1)


if __name__ == "__main__":
    main()
