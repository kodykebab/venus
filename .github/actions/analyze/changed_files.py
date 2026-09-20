#!/usr/bin/env python3
"""Lists the Solidity files a pull request touches, so a project review can be
scoped to the change instead of re-reporting the whole repo on every PR.

Prints a comma-separated list to stdout; empty output means "review everything",
which is the right fallback for a push or a manual run.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def changed_solidity_files() -> list[str]:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr_number = os.environ.get("PR_NUMBER")
    if not (token and repo and pr_number):
        return []

    files: list[str] = []
    page = 1
    while page <= 10:  # 1000 files is far past the point of a useful review
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files?per_page=100&page={page}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request) as response:
                batch = json.load(response)
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            print(f"::warning::could not list PR files ({exc}) - reviewing the whole project")
            return []

        if not batch:
            break
        for entry in batch:
            if entry.get("filename", "").endswith(".sol") and entry.get("status") != "removed":
                files.append(entry["filename"])
        if len(batch) < 100:
            break
        page += 1

    return files


if __name__ == "__main__":
    print(",".join(changed_solidity_files()))
