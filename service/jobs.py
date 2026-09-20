"""The review job: fetch a pull request's code, analyze it, report back.

Deliberately not run inside the webhook handler - GitHub wants a fast 2xx, and a
review (dependency install + compile + Slither + an LLM call) takes real time.
The handler acknowledges and enqueues; worker.py runs this afterwards, from a
durable queue so a restart mid-review resumes instead of dropping the check.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile

import httpx

import checks
import store
from github_auth import installation_token

ANALYZER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "analyzer")
sys.path.insert(0, os.path.join(ANALYZER_DIR, "static"))
sys.path.insert(0, os.path.join(ANALYZER_DIR, "llm"))

CLONE_TIMEOUT_SECONDS = 300
MAX_ANNOTATED_FINDINGS = 50


def _run_git(args: list[str], cwd: str | None = None) -> tuple[bool, str]:
    """Runs git without ever echoing the command - the clone URL carries an
    installation token."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "git timed out"
    except FileNotFoundError:
        return False, "git is not installed on the worker"
    if completed.returncode != 0:
        return False, (completed.stderr or "").strip()[-400:]
    return True, ""


def checkout_pull_request(full_name: str, pr_number: int, head_sha: str, token: str, workdir: str) -> tuple[bool, str]:
    """Shallow-fetches just the PR head. Works for fork PRs too, because
    refs/pull/N/head lives on the base repository."""
    remote = f"https://x-access-token:{token}@github.com/{full_name}.git"

    ok, err = _run_git(["init", "--quiet", workdir])
    if not ok:
        return False, f"git init failed: {err}"
    ok, err = _run_git(["remote", "add", "origin", remote], cwd=workdir)
    if not ok:
        return False, f"git remote failed: {err}"

    ok, err = _run_git(["fetch", "--depth", "1", "--quiet", "origin", f"pull/{pr_number}/head"], cwd=workdir)
    if not ok:
        # A PR from a branch on the base repo can be fetched by SHA directly.
        ok, err = _run_git(["fetch", "--depth", "1", "--quiet", "origin", head_sha], cwd=workdir)
        if not ok:
            return False, f"could not fetch the pull request head: {err}"

    ok, err = _run_git(["checkout", "--quiet", "FETCH_HEAD"], cwd=workdir)
    if not ok:
        return False, f"git checkout failed: {err}"

    # Don't leave a token sitting in .git/config on a shared worker.
    _run_git(["remote", "remove", "origin"], cwd=workdir)
    return True, ""


async def changed_solidity_files(
    full_name: str, pr_number: int, token, client: httpx.AsyncClient
) -> list[str]:
    files: list[str] = []
    page = 1
    while page <= 10:
        response = await client.get(
            f"https://api.github.com/repos/{full_name}/pulls/{pr_number}/files",
            headers=token.headers,
            params={"per_page": 100, "page": page},
        )
        if response.status_code >= 400:
            return files
        batch = response.json()
        if not batch:
            break
        files.extend(
            entry["filename"]
            for entry in batch
            if entry.get("filename", "").endswith(".sol") and entry.get("status") != "removed"
        )
        if len(batch) < 100:
            break
        page += 1
    return files


def analyze_checkout(
    workdir: str,
    changed_files: list[str],
    min_severity: str = "low",
    chain: str | None = None,
) -> dict:
    from review import review_project

    return review_project(
        workdir,
        changed_files=changed_files or None,
        min_severity=min_severity,
        install=True,
        chain=chain,
    )


def _rebase_paths(report: dict, workdir: str) -> dict:
    """review_project anchors paths at the checkout's git root, which is the
    temp directory here - strip it so annotations use repo-relative paths."""
    prefix = os.path.abspath(workdir) + os.sep
    for finding in report.get("findings", []):
        if finding.get("file", "").startswith(prefix):
            finding["file"] = finding["file"][len(prefix):]
    return report


async def run_review_job(
    installation_id: int,
    full_name: str,
    pr_number: int,
    head_sha: str,
    min_severity: str = "low",
    fail_on: str | None = None,
    chain: str | None = None,
) -> None:
    """End to end: token -> checkout -> analyze -> check run. Any failure is
    reported as a completed check explaining itself, never a silent no-op."""
    allowed, reason = store.review_allowed(installation_id)

    workdir = tempfile.mkdtemp(prefix="paracheck-")
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            token = await installation_token(installation_id, client)
        except Exception as exc:  # noqa: BLE001
            print(f"paracheck: could not mint an installation token: {exc}")
            return

        check_run_id = await checks.create_check_run(full_name, head_sha, token, client)
        if check_run_id is None:
            shutil.rmtree(workdir, ignore_errors=True)
            return

        try:
            if not allowed:
                await checks.fail_check_run(full_name, check_run_id, token, client, reason)
                return

            # git, forge/npm install and Slither are all blocking; the API
            # process may share this loop, so they belong in a thread.
            ok, error = await asyncio.to_thread(
                checkout_pull_request, full_name, pr_number, head_sha, token.token, workdir
            )
            if not ok:
                await checks.fail_check_run(full_name, check_run_id, token, client, error)
                return

            changed = await changed_solidity_files(full_name, pr_number, token, client)
            if not changed:
                await checks.complete_check_run(
                    full_name, check_run_id, token, client,
                    conclusion="success",
                    title="No Solidity changes",
                    summary="This pull request doesn't touch any .sol files.",
                )
                return

            report = _rebase_paths(
                await asyncio.to_thread(analyze_checkout, workdir, changed, min_severity, chain),
                workdir,
            )

            if report.get("unanalyzable"):
                await checks.fail_check_run(
                    full_name, check_run_id, token, client, report.get("reason", "unknown reason")
                )
                store.record_review(installation_id, full_name, pr_number, head_sha, None, 0)
                return

            findings = report.get("findings", [])
            verdict, summary = _summarize(report, changed)

            await checks.complete_check_run(
                full_name, check_run_id, token, client,
                conclusion=checks.conclusion_for(verdict, findings, fail_on),
                title=_title_for(findings),
                summary=summary,
                annotations=checks.build_annotations(findings, MAX_ANNOTATED_FINDINGS),
            )
            store.record_review(installation_id, full_name, pr_number, head_sha, verdict, len(findings))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


def _title_for(findings: list[dict]) -> str:
    if not findings:
        return "No findings"
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1
    parts = [f"{n} {sev}" for sev, n in counts.items()]
    return f"{len(findings)} finding(s): " + ", ".join(parts)


def _summarize(report: dict, changed: list[str]) -> tuple[str | None, str]:
    """Claude's synthesis when credentials are configured, the deterministic
    render otherwise. A missing key degrades the review, never breaks it."""
    from render import render_markdown

    try:
        from synthesize import render_synthesized, synthesize_review
    except ImportError:
        return None, render_markdown(report, ", ".join(changed[:3]))

    synthesized = synthesize_review(report)
    if synthesized is None:
        return None, render_markdown(report, ", ".join(changed[:3]))
    return synthesized.verdict, render_synthesized(synthesized, ", ".join(changed[:3]))
