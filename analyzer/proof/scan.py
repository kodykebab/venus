"""Runs the proof engine over a scan's findings, in place.

This is the seam between the analyzers and the proof engine. It exists to keep
two promises the plan makes: attempt proof only where it is likely to pay off
(bounded cost), and degrade to exactly today's behaviour when proof is
unavailable (no forge, no key) rather than failing a scan.

Findings arrive and leave as plain dicts - the shape the rest of the scan
pipeline already passes around - so wiring this in is one call and removing it
is one call.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "static"))

from schema import Finding  # noqa: E402

from engine import prove_finding  # noqa: E402

# The bug classes whose exploit shape is well understood enough that a generated
# PoC validates reliably - the plan's "first five classes". A finding outside
# this set is left as an unproven lead rather than spending a model call we
# expect to miss. Matched as substrings against the detector's check id.
PROVABLE_CHECKS = (
    "reentrancy",
    "arbitrary-send",
    "unchecked-transfer",
    "unchecked-lowlevel",
    "unchecked-return",
    "arithmetic",
    "integer-overflow",
    "integer-underflow",
    "tx-origin",
    "access-control",
    "unprotected",
    "suicidal",
)

# Only spend on findings that could actually block a merge, and cap how many we
# try per scan so a noisy repo cannot run up an unbounded bill.
PROVABLE_SEVERITIES = {"critical", "high", "medium"}
MAX_PROOF_ATTEMPTS = int(os.environ.get("PARACHECK_MAX_PROOF_ATTEMPTS", "5"))


def _worth_attempting(finding: dict) -> bool:
    if finding.get("evidence", "D") in ("A", "B"):
        return False  # already proven
    if finding.get("severity") not in PROVABLE_SEVERITIES:
        return False
    if not finding.get("file"):
        return False
    check = finding.get("check", "")
    return any(token in check for token in PROVABLE_CHECKS)


def prove_findings(
    findings: list[dict],
    repo: str | Path,
    api_key: str | None,
    *,
    generator=None,
    forge: str = "forge",
    max_attempts: int = MAX_PROOF_ATTEMPTS,
) -> int:
    """Attempt to promote unproven findings to tier A, mutating them in place.

    Returns how many were promoted. A no-op (returns 0) when there is no forge
    on PATH and no key - proof is an enhancement over the deterministic output,
    never a requirement for it, exactly like the LLM synthesis layer.
    """
    if generator is None:
        if shutil.which(forge) is None or not api_key:
            return 0
        from generate import claude_generator
        generator = claude_generator(api_key=api_key)

    # Most severe first, so a tight attempt budget is spent where it matters.
    order = ["critical", "high", "medium", "low", "info", "optimization"]
    candidates = sorted(
        (f for f in findings if _worth_attempting(f)),
        key=lambda f: order.index(f["severity"]) if f.get("severity") in order else len(order),
    )

    promoted = 0
    for finding in candidates[:max_attempts]:
        outcome = prove_finding(_to_finding(finding), repo, generator, forge=forge)
        if outcome.promoted:
            finding["evidence"] = outcome.finding.evidence
            finding["evidence_detail"] = outcome.finding.evidence_detail
            promoted += 1
    return promoted


def _to_finding(finding: dict) -> Finding:
    known = {f for f in Finding.__dataclass_fields__}  # tolerate extra dict keys
    return Finding(**{k: v for k, v in finding.items() if k in known})
