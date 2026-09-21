"""The polarity-flip validator: the mechanism that makes precision structural.

A candidate proof-of-concept is only trusted if it *flips*: it must fail on the
current (vulnerable) code and pass once the fix is applied - or, for an
exploit-style PoC that demonstrates the attack, pass on the vulnerable code and
fail against the fix. Either way the test's outcome has to depend on the bug.

Passing on both trees means the PoC does not actually exercise the
vulnerability (it is not pinned), and a scanner that counted it would be back to
shipping plausible-looking noise. Failing on the vulnerable tree means there is
no exploit to begin with. Only a flip is evidence, and only evidence is trusted.

This module runs `forge test` twice under a temporary patch and reports which
of those three things happened. It is deterministic and needs no model.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Verdict(str, Enum):
    VALIDATED = "validated"  # exploit reproduces and the fix stops it
    NOT_PINNED = "not_pinned"  # test passes with and without the fix
    NO_EXPLOIT = "no_exploit"  # test fails even on the vulnerable code
    ERROR = "error"  # the harness itself could not run the test


@dataclass
class ProofResult:
    verdict: Verdict
    vulnerable: str  # "PASS" | "FAIL" | "ERROR"
    patched: str  # "PASS" | "FAIL" | "ERROR"
    detail: str = ""

    @property
    def validated(self) -> bool:
        return self.verdict is Verdict.VALIDATED

    def to_evidence_detail(self, poc_test: str, command: str) -> dict:
        return {
            "poc_test": poc_test,
            "command": command,
            "vulnerable": self.vulnerable,
            "patched": self.patched,
        }


def _forge_test(repo: Path, poc_test: str, forge: str, timeout: int) -> str:
    """Run one PoC and collapse the outcome to PASS / FAIL / ERROR.

    A test that fails to compile or errors out is ERROR, distinct from a clean
    FAIL, because "the harness could not decide" must never be read as evidence.
    """
    try:
        proc = subprocess.run(
            [forge, "test", "--match-path", poc_test],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "ERROR"
    except OSError:
        return "ERROR"

    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        return "PASS"
    # forge exits non-zero both for a failing assertion and for a compile
    # error; only the former is a real FAIL we can reason about.
    if "Compiler run failed" in out or "Failed to resolve" in out or "error[" in out:
        return "ERROR"
    return "FAIL"


def validate_poc(
    repo: str | Path,
    poc_test: str,
    patch_src: str | Path,
    patch_dst: str | Path,
    *,
    forge: str = "forge",
    timeout: int = 300,
    exploit_style: bool = True,
) -> ProofResult:
    """Run `poc_test` on the vulnerable tree and on the patched tree.

    `patch_src` is the fixed source; it is copied over `patch_dst` (relative to
    the repo) to build the patched tree, then restored. `exploit_style` picks
    the flip we require: an exploit PoC passes-then-fails (the default, matching
    how the proof engine writes its PoCs); a regression-style PoC that asserts
    correct behaviour fails-then-passes.
    """
    repo = Path(repo)
    dst = repo / patch_dst
    original = dst.read_text()

    try:
        vulnerable = _forge_test(repo, poc_test, forge, timeout)
        shutil.copyfile(patch_src, dst)
        patched = _forge_test(repo, poc_test, forge, timeout)
    finally:
        dst.write_text(original)

    if vulnerable == "ERROR" or patched == "ERROR":
        return ProofResult(Verdict.ERROR, vulnerable, patched,
                           "forge could not run the PoC on one of the trees")

    want_vuln, want_patched = ("PASS", "FAIL") if exploit_style else ("FAIL", "PASS")
    if vulnerable == want_vuln and patched == want_patched:
        return ProofResult(Verdict.VALIDATED, vulnerable, patched)
    if vulnerable == want_vuln and patched == want_vuln:
        return ProofResult(Verdict.NOT_PINNED, vulnerable, patched,
                           "PoC passes with and without the fix, so it is not pinned to the bug")
    return ProofResult(Verdict.NO_EXPLOIT, vulnerable, patched,
                       "PoC does not reproduce on the vulnerable code")
