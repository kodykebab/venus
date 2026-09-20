"""`paracheck doctor` - checks the toolchain before you need it.

Every dependency here fails at a distance. A missing `forge` surfaces as
crytic-compile's "Cannot execute `forge`", a missing solc as a compile error on
a file that compiles fine, and an absent API key as a review that quietly comes
back in the plain renderer. Each of those has cost someone an hour of looking at
the wrong thing.

So: check the things that break, name the one command that fixes each, and say
plainly which failures actually stop a review and which only degrade it.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys

OK = "ok"
WARN = "warn"
FAIL = "fail"

MARKS = {OK: "✓", WARN: "!", FAIL: "✗"}


class Check:
    def __init__(self, name: str, status: str, detail: str, fix: str = "") -> None:
        self.name = name
        self.status = status
        self.detail = detail
        self.fix = fix

    def as_dict(self) -> dict:
        return {"check": self.name, "status": self.status, "detail": self.detail, "fix": self.fix}


def _version_of(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    output = (completed.stdout or completed.stderr).strip()
    if not output:
        return ""
    lines = output.splitlines()
    # solc prints a banner first and the version on the next line; forge, node
    # and git all put it on the first.
    for line in lines:
        if "Version:" in line:
            return line.split("Version:", 1)[1].strip()
    return lines[0]


def check_python() -> Check:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info < (3, 10):
        return Check("python", FAIL, f"{version} - Slither needs 3.10+",
                     "install a newer Python and rebuild the venv")
    return Check("python", OK, f"{version} at {sys.executable}")


def check_packages() -> list[Check]:
    checks = []
    for module, package, required in (
        ("slither", "slither-analyzer", True),
        ("crytic_compile", "crytic-compile", True),
        ("anthropic", "anthropic", False),
    ):
        try:
            loaded = importlib.import_module(module)
            version = getattr(loaded, "__version__", "")
            checks.append(Check(package, OK, version or "installed"))
        except ImportError:
            checks.append(Check(
                package,
                FAIL if required else WARN,
                "not importable from this interpreter",
                f"pip install {package}" if required
                else f"pip install {package}  # only needed for written summaries",
            ))
    return checks


def check_solc() -> Check:
    solc = shutil.which("solc")
    if solc is None:
        return Check("solc", FAIL, "not on PATH",
                     "solc-select install 0.8.24 && solc-select use 0.8.24")
    version = _version_of(["solc", "--version"])
    if version is None:
        # Usually a solc-select shim with no version selected, or the wrong
        # architecture - both look like "installed" until something runs it.
        return Check("solc", FAIL, f"{solc} is present but won't run",
                     "solc-select use 0.8.24 --always-install")
    return Check("solc", OK, f"{version} at {solc}")


def check_forge() -> Check:
    """Not optional for project mode: without forge, crytic-compile can't build
    a foundry project and every review of one returns 'unanalyzable'."""
    if shutil.which("forge") is None:
        return Check("forge", FAIL, "not on PATH - foundry projects cannot be compiled",
                     "curl -L https://foundry.paradigm.xyz | bash && foundryup")
    version = _version_of(["forge", "--version"])
    return Check("forge", OK, f"{version} at {shutil.which('forge')}" if version else "installed")


def check_node() -> Check:
    if shutil.which("node") is None:
        return Check("node", WARN, "not on PATH - hardhat and truffle projects can't be built",
                     "install Node 20+ (only needed for hardhat/truffle repos)")
    return Check("node", OK, _version_of(["node", "--version"]) or "installed")


def check_llm() -> Check:
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "llm"))
        from synthesize import credentials_available
    except ImportError:
        return Check("claude api", WARN, "synthesize module not importable",
                     "reviews still render, just without the written summary")

    if credentials_available():
        return Check("claude api", OK, "credentials found")
    return Check("claude api", WARN, "no credentials - reviews render from findings directly",
                 "put ANTHROPIC_API_KEY=sk-ant-... in .env (create one at "
                 "https://console.anthropic.com/settings/keys)")


def check_git() -> Check:
    if shutil.which("git") is None:
        return Check("git", WARN, "not on PATH - dependency installs will fail",
                     "install git")
    return Check("git", OK, _version_of(["git", "--version"]) or "installed")


def run_checks() -> list[Check]:
    return [
        check_python(),
        *check_packages(),
        check_solc(),
        check_forge(),
        check_node(),
        check_git(),
        check_llm(),
    ]


def render(checks: list[Check]) -> str:
    width = max(len(c.name) for c in checks)
    lines = []
    for check in checks:
        lines.append(f"  {MARKS[check.status]} {check.name.ljust(width)}  {check.detail}")
        if check.fix and check.status != OK:
            lines.append(f"    {' ' * width}  -> {check.fix}")

    failures = [c for c in checks if c.status == FAIL]
    warnings = [c for c in checks if c.status == WARN]

    lines.append("")
    if failures:
        lines.append(f"{len(failures)} blocking problem(s): reviews will not run until these are fixed.")
    elif warnings:
        lines.append(f"Ready. {len(warnings)} optional component(s) missing - "
                     "reviews run, with reduced output.")
    else:
        lines.append("Ready. Everything is installed.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    checks = run_checks()

    if "--json" in argv:
        print(json.dumps({"checks": [c.as_dict() for c in checks]}, indent=2))
    else:
        print("paracheck doctor\n")
        print(render(checks))

    # Exit non-zero only on a blocking failure - a missing API key is not a
    # reason for CI to go red.
    return 1 if any(c.status == FAIL for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
