"""Detects and prepares a real Solidity project so Slither can compile it.

The single-file path (`load_slither`) can't resolve `import` statements, which
rules out essentially every real repo - they all import OpenZeppelin, forge-std,
or their own interfaces. This module handles the multi-file case: work out which
build system a checkout uses, fetch its dependencies, and hand Slither the
project rather than a lone file.

Dependency installation runs third-party build tooling, so every subprocess here
is bounded by a timeout and callers are expected to run it somewhere disposable
(a CI runner, a container) rather than on a developer's main machine.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

INSTALL_TIMEOUT_SECONDS = 600


@dataclass
class Project:
    root: str
    framework: str  # "foundry" | "hardhat" | "truffle" | "plain"
    source_dir: str

    @property
    def is_installable(self) -> bool:
        return self.framework in ("foundry", "hardhat", "truffle")


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def detect_project(root: str) -> Project:
    """Works out the build system from the files a checkout actually has."""
    root = os.path.abspath(root)
    has = lambda name: os.path.exists(os.path.join(root, name))  # noqa: E731

    if has("foundry.toml"):
        src = "src"
        config = _read(os.path.join(root, "foundry.toml"))
        for line in config.splitlines():
            stripped = line.strip()
            if stripped.startswith("src") and "=" in stripped:
                src = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                break
        return Project(root, "foundry", src)

    if has("hardhat.config.js") or has("hardhat.config.ts"):
        return Project(root, "hardhat", "contracts")

    if has("truffle-config.js") or has("truffle.js"):
        return Project(root, "truffle", "contracts")

    return Project(root, "plain", ".")


def _run(command: list[str], cwd: str) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=INSTALL_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return False, f"{command[0]} is not installed"
    except subprocess.TimeoutExpired:
        return False, f"{' '.join(command)} timed out after {INSTALL_TIMEOUT_SECONDS}s"

    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "").strip().splitlines()[-5:]
        return False, f"{' '.join(command)} failed: " + " / ".join(tail)
    return True, ""


def install_dependencies(project: Project) -> tuple[bool, str]:
    """Fetches the project's dependencies so imports resolve. Returns (ok, reason).

    A failure here is reported, not raised - a repo whose dependencies won't
    install should produce a clear "couldn't build this" review, not a crash."""
    if project.framework == "foundry":
        # A repo vendoring its libs already (committed lib/) needs no fetch.
        if os.path.isdir(os.path.join(project.root, "lib")) and os.listdir(
            os.path.join(project.root, "lib")
        ):
            return True, "lib/ already present"
        return _run(["forge", "install"], project.root)

    if project.framework in ("hardhat", "truffle"):
        if os.path.isdir(os.path.join(project.root, "node_modules")):
            return True, "node_modules/ already present"
        lockfile = os.path.join(project.root, "package-lock.json")
        command = ["npm", "ci"] if os.path.exists(lockfile) else ["npm", "install"]
        return _run(command, project.root)

    return True, "no dependency step needed"
