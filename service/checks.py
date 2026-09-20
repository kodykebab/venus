"""Checks API integration: the pass/fail status and inline annotations that make
a review show up inside GitHub's own PR UI rather than as an external report.

A check run is created as `in_progress` the moment a job starts - so the PR shows
something is happening - and patched to `completed` with annotations when the
analysis finishes.
"""
from __future__ import annotations

import httpx

from github_auth import GITHUB_API, InstallationToken

CHECK_NAME = "ParaCheck"

# GitHub rejects a request carrying more than 50 annotations.
MAX_ANNOTATIONS_PER_REQUEST = 50

_SEVERITY_TO_LEVEL = {
    "critical": "failure",
    "high": "failure",
    "medium": "warning",
    "low": "warning",
    "info": "notice",
    "optimization": "notice",
}

_VERDICT_TO_CONCLUSION = {
    "request_changes": "failure",
    "comment": "neutral",
    "approve": "success",
}


def annotation_level(severity: str) -> str:
    return _SEVERITY_TO_LEVEL.get(severity, "notice")


def conclusion_for(verdict: str | None, findings: list[dict], fail_on: str | None = None) -> str:
    """A synthesized verdict wins when present; otherwise fall back to whether
    anything crossed the configured severity gate."""
    if verdict in _VERDICT_TO_CONCLUSION:
        return _VERDICT_TO_CONCLUSION[verdict]
    if fail_on:
        order = ["critical", "high", "medium", "low", "info", "optimization"]
        threshold = order.index(fail_on) if fail_on in order else len(order)
        if any(order.index(f["severity"]) <= threshold for f in findings if f["severity"] in order):
            return "failure"
    return "neutral" if findings else "success"


def build_annotations(findings: list[dict], limit: int = MAX_ANNOTATIONS_PER_REQUEST) -> list[dict]:
    """One inline annotation per finding, anchored to the flagged line - this is
    what puts the comment on the right line of the diff instead of in a wall of
    text at the bottom of the PR."""
    annotations = []
    for finding in findings[:limit]:
        if not finding.get("file") or not finding.get("lines"):
            continue
        lines = finding["lines"]
        message = finding.get("description") or finding.get("title") or ""
        if finding.get("suggested_fix"):
            message = f"{message}\n\nSuggested fix: {finding['suggested_fix']}"
        annotations.append(
            {
                "path": finding["file"],
                "start_line": lines[0],
                "end_line": lines[-1] if len(lines) > 1 else lines[0],
                "annotation_level": annotation_level(finding["severity"]),
                "title": f"{finding['check']} ({finding['severity']})",
                # GitHub truncates long annotation messages; keep them readable.
                "message": message[:4000],
            }
        )
    return annotations


async def create_check_run(
    full_name: str,
    head_sha: str,
    token: InstallationToken,
    client: httpx.AsyncClient,
) -> int | None:
    response = await client.post(
        f"{GITHUB_API}/repos/{full_name}/check-runs",
        headers=token.headers,
        json={"name": CHECK_NAME, "head_sha": head_sha, "status": "in_progress"},
    )
    if response.status_code >= 400:
        print(f"paracheck: could not create check run ({response.status_code}): {response.text[:200]}")
        return None
    return response.json().get("id")


async def complete_check_run(
    full_name: str,
    check_run_id: int,
    token: InstallationToken,
    client: httpx.AsyncClient,
    *,
    conclusion: str,
    title: str,
    summary: str,
    annotations: list[dict] | None = None,
) -> bool:
    payload = {
        "status": "completed",
        "conclusion": conclusion,
        "output": {
            "title": title,
            "summary": summary[:65000],
            "annotations": (annotations or [])[:MAX_ANNOTATIONS_PER_REQUEST],
        },
    }
    response = await client.patch(
        f"{GITHUB_API}/repos/{full_name}/check-runs/{check_run_id}",
        headers=token.headers,
        json=payload,
    )
    if response.status_code >= 400:
        print(f"paracheck: could not complete check run ({response.status_code}): {response.text[:200]}")
        return False
    return True


async def fail_check_run(
    full_name: str,
    check_run_id: int,
    token: InstallationToken,
    client: httpx.AsyncClient,
    reason: str,
) -> None:
    """Used when the analysis itself couldn't run. A check that silently never
    completes is worse than one that says why it stopped."""
    await complete_check_run(
        full_name,
        check_run_id,
        token,
        client,
        conclusion="neutral",
        title="ParaCheck could not analyze this change",
        summary=reason,
    )
