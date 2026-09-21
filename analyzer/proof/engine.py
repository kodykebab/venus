"""The proof engine: turns an unproven lead into proven evidence, or leaves it
honestly unproven.

Given a finding and the repository it was found in, the engine asks a generator
for two things: a Foundry proof-of-concept that exercises the bug, and a
candidate fix for the offending source. It then runs the polarity-flip
validator (validate.py): the PoC must pass on the current code and fail against
the proposed fix. Only if it flips is the finding promoted to evidence tier A,
carrying the exact command a developer can run to see it for themselves.

Nothing here trusts the generator's word. A model can be confident and wrong;
`forge test` cannot. The generator is a plain callable so the loop is testable
with a canned PoC, and the real one (the Claude API) drops in without changing
the control flow.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "static"))

from schema import Finding  # noqa: E402

from validate import Verdict, validate_poc  # noqa: E402


@dataclass
class Candidate:
    """What a generator proposes for one finding."""
    poc_filename: str  # e.g. "test/PocReentrancy.t.sol", relative to the repo
    poc_source: str  # the Solidity test body
    fix_target: str  # the source file the fix replaces, relative to the repo
    fixed_source: str  # the full patched contents of fix_target


# A generator sees the finding and the repo root, and returns a candidate, or
# None when it has nothing to try (the honest outcome for a bug it cannot shape
# into an exploit - which the plan's own experiment showed will happen).
Generator = Callable[[Finding, Path], "Candidate | None"]


@dataclass
class ProofOutcome:
    finding: Finding  # promoted to tier A, or returned unchanged
    promoted: bool
    reason: str


def prove_finding(
    finding: Finding,
    repo: str | Path,
    generator: Generator,
    *,
    forge: str = "forge",
    timeout: int = 300,
    keep_poc_on_success: bool = True,
) -> ProofOutcome:
    """Attempt to promote one finding to proven. Never raises on a bad
    candidate: a generator that produces a non-compiling or non-pinned PoC
    leaves the finding exactly as unproven as it was."""
    repo = Path(repo)

    try:
        candidate = generator(finding, repo)
    except Exception as exc:  # a generator failure is a miss, not a crash
        return ProofOutcome(finding, False, f"generator error: {exc}")

    if candidate is None:
        return ProofOutcome(finding, False, "generator produced no candidate")

    poc_path = repo / candidate.poc_filename
    fix_tmp = repo / (candidate.fix_target + ".paracheck-fix")
    validated = False
    try:
        poc_path.parent.mkdir(parents=True, exist_ok=True)
        poc_path.write_text(candidate.poc_source)
        fix_tmp.write_text(candidate.fixed_source)

        result = validate_poc(
            repo,
            candidate.poc_filename,
            fix_tmp,
            candidate.fix_target,
            forge=forge,
            timeout=timeout,
            exploit_style=True,
        )
        validated = result.verdict is Verdict.VALIDATED
    except Exception as exc:  # keep the promise: a bad candidate is a miss
        return ProofOutcome(finding, False, f"validation error: {exc}")
    finally:
        fix_tmp.unlink(missing_ok=True)
        # Keep the PoC on disk only when it earned tier A, so the printed
        # `forge test` command actually runs; otherwise clean it away.
        if not (validated and keep_poc_on_success):
            poc_path.unlink(missing_ok=True)

    if not validated:
        # Leave the finding unproven, and say why - a not-pinned PoC is exactly
        # the case the validator exists to catch.
        return ProofOutcome(finding, False, f"not promoted: {result.verdict.value} "
                                            f"(vulnerable={result.vulnerable}, patched={result.patched})")

    command = f"forge test --match-path {candidate.poc_filename}"
    promoted = replace(
        finding,
        evidence="A",
        evidence_detail=result.to_evidence_detail(candidate.poc_filename, command),
    )
    return ProofOutcome(promoted, True, "promoted to tier A")
