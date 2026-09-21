#!/usr/bin/env python3
"""Runs a ParaCheck scan inside a GitHub Actions job.

The analysis happens here, on the customer's runner, so ParaCheck's servers
never receive a copy of the source. This script:

  1. analyses the checkout,
  2. posts the result as a Check Run using the workflow's own GITHUB_TOKEN,
  3. reports the outcome back to the ParaCheck API so it appears on the
     dashboard and counts against the weekly quota,
  4. sets the job's exit code from the configured `fail-on` threshold.

Step 3 is best-effort. A dashboard that missed an update is a much smaller
problem than a check that never appeared on the pull request, so a reporting
failure is logged and the job carries on.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

PARACHECK = os.path.join(os.environ.get("GITHUB_WORKSPACE", "."), ".paracheck")
sys.path.insert(0, os.path.join(PARACHECK, "analyzer"))
sys.path.insert(0, os.path.join(PARACHECK, "analyzer", "static"))
sys.path.insert(0, os.path.join(PARACHECK, "analyzer", "llm"))

# Reuse the analyzer's own Check Run helpers rather than a second copy of them.
from server import (  # noqa: E402
    build_annotations,
    complete_check_run,
    conclusion_for,
    create_check_run,
    solidity_files,
    summarize,
)

SEVERITY_ORDER = ["critical", "high", "medium", "low", "info", "optimization"]


def event() -> dict:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def changed_files(payload: dict, repository: str, token: str) -> list[str]:
    """The .sol files this pull request touches, so findings are scoped to the
    change rather than to a backlog nobody in this PR wrote."""
    number = (payload.get("pull_request") or {}).get("number")
    if not number:
        return []

    changed: list[str] = []
    for page in range(1, 11):
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repository}/pulls/{number}/files"
            f"?per_page=100&page={page}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "paracheck-action",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                batch = json.loads(response.read())
        except (urllib.error.URLError, OSError, ValueError):
            return changed
        if not batch:
            break
        changed += [
            f["filename"] for f in batch
            if f.get("filename", "").endswith(".sol") and f.get("status") != "removed"
        ]
        if len(batch) < 100:
            break
    return changed


def report(state: str, findings: int = 0, verdict: str | None = None, message: str = "") -> None:
    api = os.environ.get("API_URL", "")
    scan_id = os.environ.get("SCAN_ID", "")
    oidc = os.environ.get("OIDC", "")
    if not (api and scan_id and oidc):
        return

    request = urllib.request.Request(
        f"{api}/api/runs/result",
        method="POST",
        data=json.dumps({
            "scanId": scan_id,
            "state": state,
            "findings": findings,
            "verdict": verdict,
            "message": message[:400],
        }).encode(),
        headers={"Authorization": f"Bearer {oidc}", "content-type": "application/json"},
    )
    try:
        urllib.request.urlopen(request, timeout=30).read()
    except (urllib.error.URLError, OSError) as exc:
        # Never fail the job over this: the check is already on the pull request.
        print(f"::warning title=ParaCheck::Could not update the dashboard ({exc}).")


def main() -> int:
    repository = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    target = os.environ.get("TARGET", ".")
    chain = os.environ.get("CHAIN", "monad")
    min_severity = os.environ.get("MIN_SEVERITY", "low")
    fail_on = (os.environ.get("FAIL_ON") or "").strip()

    payload = event()
    head_sha = ((payload.get("pull_request") or {}).get("head") or {}).get("sha") \
        or os.environ.get("GITHUB_SHA", "")

    workspace = os.environ.get("GITHUB_WORKSPACE", ".")
    root = os.path.abspath(os.path.join(workspace, target))

    scoped = changed_files(payload, repository, token)
    if not scoped:
        if payload.get("pull_request"):
            print("ParaCheck: this pull request doesn't touch any .sol files.")
            report("empty", message="No Solidity changes.")
            return 0
        scoped = solidity_files(root)
        if not scoped:
            print("ParaCheck: no .sol files found outside dependencies.")
            report("empty", message="No Solidity files found.")
            return 0

    check_run_id = create_check_run(repository, head_sha, token) if head_sha else None

    import sandbox
    from review import review_project

    # Compiling runs the repository's own build system, so it gets a scrubbed
    # environment rather than this job's - which holds GITHUB_TOKEN and, when
    # the account supplied one, an Anthropic key.
    with sandbox.scrubbed_environ(root):
        report_data = review_project(
            root, changed_files=scoped or None,
            min_severity=min_severity, install=True, chain=chain,
        )

    prefix = os.path.abspath(workspace) + os.sep
    for finding in report_data.get("findings", []):
        if finding.get("file", "").startswith(prefix):
            finding["file"] = finding["file"][len(prefix):]

    if report_data.get("unanalyzable"):
        reason = report_data.get("reason", "unknown reason")
        print(f"::warning title=ParaCheck::{reason}")
        if check_run_id:
            complete_check_run(repository, check_run_id, token, conclusion="neutral",
                               title="Could not analyse this change", summary=reason)
        report("failed", message=reason)
        return 0  # a project we cannot build is not a failing review

    findings = report_data.get("findings", [])
    verdict, summary = summarize(report_data, ", ".join(scoped[:3]),
                                 os.environ.get("ANTHROPIC_API_KEY") or None)

    conclusion = conclusion_for(findings, fail_on or None)
    if check_run_id:
        complete_check_run(
            repository, check_run_id, token,
            conclusion=conclusion,
            title=(f"{len(findings)} optimisation "
                   f"{'opportunity' if len(findings) == 1 else 'opportunities'}"
                   if findings else "No findings"),
            summary=summary,
            annotations=build_annotations(findings),
        )

    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
        handle.write(f"findings={len(findings)}\n")

    report("done", findings=len(findings), verdict=verdict,
           message=f"{len(findings)} opportunit{'y' if len(findings) == 1 else 'ies'} found.")

    print(summary)
    return 1 if conclusion == "failure" else 0


if __name__ == "__main__":
    raise SystemExit(main())
