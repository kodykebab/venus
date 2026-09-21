"""The analyzer container's HTTP interface.

This is the compute plane. It is the only part of ParaCheck that sees customer
source, and running a scan means running the repository's own build system -
`forge install` runs git hooks, `npm install` runs postinstall scripts - so
everything here treats the checkout as hostile input.

Two layers of containment, neither sufficient alone:

  * The container's egress allowlist (see cloudflare/src/analyzer.ts) means a
    script that steals a secret has nowhere to send it.
  * sandbox.py scrubs the environment every build tool inherits, so there is
    little worth stealing in the first place, and caps CPU, memory, file size
    and process count.

Stdlib HTTP rather than FastAPI: this serves one route to one caller inside a
private network, and a smaller image is a smaller attack surface.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "static"))
sys.path.insert(0, os.path.join(HERE, "llm"))

import sandbox  # noqa: E402  (after sys.path is set up)

PORT = int(os.environ.get("PORT", "8080"))
CLONE_TIMEOUT_SECONDS = int(os.environ.get("PARACHECK_CLONE_TIMEOUT", "300"))
MAX_ANNOTATIONS = 50
GITHUB_API = "https://api.github.com"

MIN_SEVERITY = os.environ.get("PARACHECK_MIN_SEVERITY", "low")
FAIL_ON = os.environ.get("PARACHECK_FAIL_ON") or None
CHAIN = os.environ.get("PARACHECK_CHAIN", "monad")

# Dependency directories are skipped rather than left for the analyzer to
# discard: on a repo vendoring OpenZeppelin this is the difference between
# analysing a handful of files and several hundred.
SKIP_DIRECTORIES = {"lib", "node_modules", "out", "cache", "artifacts", "forge-std", ".git"}


# --- git --------------------------------------------------------------------

def _git(args: list[str], cwd: str | None = None) -> tuple[bool, str]:
    """Runs git without ever echoing the command - the clone URL carries a token."""
    try:
        completed = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True,
            timeout=CLONE_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "git timed out"
    except FileNotFoundError:
        return False, "git is not installed in the analyzer image"
    if completed.returncode != 0:
        return False, (completed.stderr or "").strip()[-400:]
    return True, ""


def checkout(repository: str, token: str, pull_request: int | None,
             head_sha: str | None, workdir: str) -> tuple[bool, str, str]:
    """Fetches exactly what is being scanned. Returns (ok, error, head_sha)."""
    remote = f"https://x-access-token:{token}@github.com/{repository}.git"

    if pull_request is None:
        ok, err = _git(["clone", "--depth", "1", "--quiet", remote, workdir])
        if not ok:
            return False, f"could not clone the repository: {err}", ""
    else:
        ok, err = _git(["init", "--quiet", workdir])
        if not ok:
            return False, f"git init failed: {err}", ""
        ok, err = _git(["remote", "add", "origin", remote], cwd=workdir)
        if not ok:
            return False, f"git remote failed: {err}", ""
        # refs/pull/N/head lives on the base repository, so this works for fork
        # pull requests too.
        ok, err = _git(["fetch", "--depth", "1", "--quiet", "origin",
                        f"pull/{pull_request}/head"], cwd=workdir)
        if not ok and head_sha:
            ok, err = _git(["fetch", "--depth", "1", "--quiet", "origin", head_sha], cwd=workdir)
        if not ok:
            return False, f"could not fetch the pull request head: {err}", ""
        ok, err = _git(["checkout", "--quiet", "FETCH_HEAD"], cwd=workdir)
        if not ok:
            return False, f"git checkout failed: {err}", ""

    resolved = head_sha or ""
    if not resolved:
        try:
            completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=workdir,
                                       capture_output=True, text=True, timeout=30, check=False)
            resolved = completed.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            resolved = ""

    # Never leave a token sitting in .git/config where a build script could read it.
    _git(["remote", "remove", "origin"], cwd=workdir)
    return True, "", resolved


def solidity_files(workdir: str) -> list[str]:
    found = []
    for root, directories, files in os.walk(workdir):
        directories[:] = [d for d in directories
                          if d not in SKIP_DIRECTORIES and not d.startswith(".")]
        for name in files:
            if name.endswith(".sol"):
                found.append(os.path.relpath(os.path.join(root, name), workdir))
    return sorted(found)


def changed_solidity_files(repository: str, pull_request: int, token: str) -> list[str]:
    """Files the pull request touches, so findings are scoped to the change
    rather than to an inherited backlog nobody edited."""
    changed: list[str] = []
    for page in range(1, 11):  # 3000 files is far past the point of usefulness
        request = urllib.request.Request(
            f"{GITHUB_API}/repos/{repository}/pulls/{pull_request}/files"
            f"?per_page=300&page={page}",
            headers=_github_headers(token),
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                batch = json.loads(response.read())
        except (urllib.error.URLError, OSError, ValueError):
            return changed
        if not batch:
            break
        changed.extend(
            f["filename"] for f in batch
            if f.get("filename", "").endswith(".sol") and f.get("status") != "removed"
        )
        if len(batch) < 300:
            break
    return changed


# --- GitHub Checks ----------------------------------------------------------

def _github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "paracheck-analyzer",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github(method: str, path: str, token: str, body: dict) -> dict | None:
    request = urllib.request.Request(
        f"{GITHUB_API}{path}", method=method,
        data=json.dumps(body).encode(), headers=_github_headers(token),
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        print(f"analyzer: github {method} {path} -> {exc.code} {exc.read()[:200]!r}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"analyzer: github {method} {path} failed: {exc}")
    return None


def create_check_run(repository: str, head_sha: str, token: str) -> int | None:
    result = _github("POST", f"/repos/{repository}/check-runs", token, {
        "name": "ParaCheck",
        "head_sha": head_sha,
        "status": "in_progress",
        "output": {
            "title": "Analysing",
            "summary": "Looking for expensive storage, execution and parallelism patterns.",
        },
    })
    return result.get("id") if result else None


def complete_check_run(repository: str, check_run_id: int, token: str, *,
                       conclusion: str, title: str, summary: str,
                       annotations: list | None = None) -> None:
    _github("PATCH", f"/repos/{repository}/check-runs/{check_run_id}", token, {
        "status": "completed",
        "conclusion": conclusion,
        "output": {
            "title": title,
            "summary": summary,
            # The Checks API takes at most 50 per request, and more than that in
            # one review is noise anyway.
            "annotations": (annotations or [])[:MAX_ANNOTATIONS],
        },
    })


SEVERITY_TO_LEVEL = {
    "critical": "failure", "high": "failure",
    "medium": "warning", "low": "warning",
    "info": "notice", "optimization": "notice",
}


def build_annotations(findings: list[dict]) -> list[dict]:
    annotations = []
    for finding in findings[:MAX_ANNOTATIONS]:
        path = finding.get("file")
        line = finding.get("line")
        if not path or not line:
            continue
        annotations.append({
            "path": path,
            "start_line": int(line),
            "end_line": int(line),
            "annotation_level": SEVERITY_TO_LEVEL.get(finding.get("severity", ""), "notice"),
            "title": finding.get("check", "Finding"),
            "message": finding.get("message", ""),
        })
    return annotations


def conclusion_for(findings: list[dict], fail_on: str | None) -> str:
    """Only proven findings can fail a check.

    This is the whole promise of the product in one place: an unproven pattern
    match, however severe it looks, is a lead - it is shown, but it never
    blocks a merge. A developer's build breaks only for something that
    reproduced (a failing exploit test, tier A, or a symbolic counterexample,
    tier B). That is what makes a red check here worth trusting instead of
    ignoring, which is the failure mode of every noisy scanner before it.
    """
    proven = [f for f in findings if f.get("evidence", "D") in ("A", "B")]

    if not fail_on:
        # No threshold configured: surface that there is something (neutral)
        # without ever blocking, and pass cleanly when there is nothing.
        return "success" if not findings else "neutral"

    order = ["critical", "high", "medium", "low", "info", "optimization"]
    try:
        threshold = order.index(fail_on)
    except ValueError:
        return "neutral"
    blocking = [f for f in proven
                if f.get("severity") in order and order.index(f["severity"]) <= threshold]
    return "failure" if blocking else "success"


# --- the scan ---------------------------------------------------------------

def summarize(report: dict, target: str, anthropic_key: str | None) -> tuple[str | None, str]:
    """A written summary when the account supplied a Claude key, the
    deterministic render otherwise. Missing credentials degrade the output,
    never the findings."""
    from render import render_markdown

    if anthropic_key:
        try:
            from synthesize import render_synthesized, synthesize_review

            synthesized = synthesize_review(report, api_key=anthropic_key)
            if synthesized is not None:
                return synthesized.verdict, render_synthesized(synthesized, target)
        except Exception as exc:  # noqa: BLE001 - never fail a scan over synthesis
            print(f"analyzer: synthesis unavailable ({type(exc).__name__}), rendering findings")
    return None, render_markdown(report, target)


def check_run_title(total: int, proven: int) -> str:
    """The check-run headline leads with what reproduces, because that is the
    number worth a developer's attention."""
    if total == 0:
        return "No findings"
    if proven == 0:
        return f"{total} unproven lead{'' if total == 1 else 's'}"
    leads = total - proven
    tail = f", {leads} lead{'' if leads == 1 else 's'}" if leads else ""
    return f"{proven} proven finding{'' if proven == 1 else 's'}{tail}"


def scan_message(total: int, proven: int) -> str:
    if total == 0:
        return "No findings."
    if proven == 0:
        return f"{total} unproven lead{'' if total == 1 else 's'}."
    return f"{proven} proven, {total - proven} lead{'' if total - proven == 1 else 's'}."


def run_scan(job: dict) -> dict:
    repository = job["repository"]
    token = job["githubToken"]
    pull_request = job.get("pullRequest")
    workdir = tempfile.mkdtemp(prefix="paracheck-scan-")
    check_run_id = None

    try:
        ok, error, head_sha = checkout(repository, token, pull_request,
                                       job.get("headSha"), workdir)
        if not ok:
            return {"state": "failed", "message": error}

        check_run_id = create_check_run(repository, head_sha, token) if head_sha else None

        if pull_request is not None:
            targets = changed_solidity_files(repository, pull_request, token)
            if not targets:
                if check_run_id:
                    complete_check_run(repository, check_run_id, token,
                                       conclusion="success", title="No Solidity changes",
                                       summary="This pull request doesn't touch any .sol files.")
                return {"state": "empty", "message": "No Solidity changes."}
        else:
            targets = solidity_files(workdir)
            if not targets:
                if check_run_id:
                    complete_check_run(repository, check_run_id, token,
                                       conclusion="neutral", title="No Solidity found",
                                       summary="This repository has no .sol files outside its dependencies.")
                return {"state": "empty", "message": "No Solidity files found."}

        from review import review_project

        # Compiling the repository runs its own build system, so it inherits a
        # scrubbed environment rather than this process's.
        with sandbox.scrubbed_environ(workdir):
            report = review_project(workdir, changed_files=targets or None,
                                    min_severity=MIN_SEVERITY, install=True, chain=CHAIN)

        prefix = os.path.abspath(workdir) + os.sep
        for finding in report.get("findings", []):
            if finding.get("file", "").startswith(prefix):
                finding["file"] = finding["file"][len(prefix):]

        # Attempt to prove what can be proven. This is what promotes a finding
        # from an unproven lead to tier A - a generated exploit test that fails
        # on this code and passes against its fix. Runs inside the same scrubbed
        # environment as the build, and no-ops without forge or a key, so a scan
        # never depends on it.
        try:
            from proof.scan import prove_findings

            with sandbox.scrubbed_environ(workdir):
                proven = prove_findings(report.get("findings", []), workdir, job.get("anthropicKey"))
            if proven:
                print(f"analyzer: promoted {proven} finding(s) to proven with a reproducing PoC")
        except Exception as exc:  # proof is an enhancement, never a scan blocker
            print(f"analyzer: proof step skipped ({type(exc).__name__}: {exc})")

        if report.get("unanalyzable"):
            reason = report.get("reason", "unknown reason")
            if check_run_id:
                complete_check_run(repository, check_run_id, token, conclusion="neutral",
                                   title="Could not analyse this change", summary=reason)
            return {"state": "failed", "message": reason}

        findings = report.get("findings", [])
        target = ", ".join(targets[:3])
        verdict, summary = summarize(report, target, job.get("anthropicKey"))

        proven_count = sum(1 for f in findings if f.get("evidence", "D") in ("A", "B"))

        if check_run_id:
            complete_check_run(
                repository, check_run_id, token,
                conclusion=conclusion_for(findings, FAIL_ON),
                title=check_run_title(len(findings), proven_count),
                summary=summary,
                annotations=build_annotations(findings),
            )

        return {
            "state": "done",
            "findings": len(findings),
            "provenFindings": proven_count,
            "verdict": verdict,
            "headSha": head_sha,
            "message": scan_message(len(findings), proven_count),
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# --- HTTP -------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's interface
        if self.path == "/health":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/scan":
            self._send(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("content-length", "0"))
            job = json.loads(self.rfile.read(length))
        except (ValueError, OSError):
            self._send(400, {"error": "invalid job"})
            return

        if not job.get("repository") or not job.get("githubToken"):
            self._send(400, {"error": "repository and githubToken are required"})
            return

        try:
            self._send(200, run_scan(job))
        except Exception as exc:  # noqa: BLE001 - one bad scan must not kill the container
            traceback.print_exc()
            self._send(200, {"state": "failed",
                             "message": f"{type(exc).__name__}: {exc}"[:400]})

    def log_message(self, fmt: str, *args) -> None:
        # The default logs the full request line, which would put a token in the
        # logs if one ever moved into a query string.
        print(f"analyzer: {fmt % args}")


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"analyzer: listening on {PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
