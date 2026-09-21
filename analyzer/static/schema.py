"""Unified finding schema shared by every ParaCheck analyzer.

The parallelism classifier and Slither's built-in detector suite produce very
different native shapes; both normalize into `Finding` so downstream consumers
(the CLI, the GitHub Action, the LLM synthesis layer, the web UI) only ever deal
with one structure.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Ordered most severe first - index into this for sorting/filtering.
SEVERITIES = ["critical", "high", "medium", "low", "info", "optimization"]

# Evidence tiers, strongest first. This is the spine of the product: a finding
# is trusted according to what can be shown for it, not according to how
# confident a detector or model feels.
#
#   A  a Foundry test that fails on this code and passes against the fix
#   B  a symbolic counterexample with concrete inputs
#   C  a proven-reachable path from a public entrypoint, guards enumerated
#   D  a pattern or heuristic match, unproven
#
# Only A and B are "proven": they alone may surface at the top of a report and
# block a merge. C and D are real information for a human sweeping the code, but
# they are never allowed to interrupt anyone, and D is always labelled unproven.
EVIDENCE_TIERS = ["A", "B", "C", "D"]
EVIDENCE_LABEL = {
    "A": "Proven (exploit test)",
    "B": "Proven (symbolic counterexample)",
    "C": "Reachable",
    "D": "Unproven",
}
_PROVEN_TIERS = {"A", "B"}


def evidence_rank(tier: str) -> int:
    """Lower is stronger evidence. Unknown tiers sort last."""
    try:
        return EVIDENCE_TIERS.index(tier)
    except ValueError:
        return len(EVIDENCE_TIERS)


def is_proven(tier: str) -> bool:
    """A proven finding (A or B) may surface top-level and block a merge."""
    return tier in _PROVEN_TIERS

# Slither reports impact as a human string; map it onto our scale.
_SLITHER_IMPACT_TO_SEVERITY = {
    "High": "high",
    "Medium": "medium",
    "Low": "low",
    "Informational": "info",
    "Optimization": "optimization",
}


def severity_rank(severity: str) -> int:
    """Lower is more severe. Unknown severities sort last."""
    try:
        return SEVERITIES.index(severity)
    except ValueError:
        return len(SEVERITIES)


def severity_from_slither_impact(impact: str) -> str:
    return _SLITHER_IMPACT_TO_SEVERITY.get(impact, "info")


def at_least(severity: str, minimum: str) -> bool:
    """True if `severity` is at least as severe as `minimum`."""
    return severity_rank(severity) <= severity_rank(minimum)


@dataclass
class Finding:
    source: str  # which analyzer produced it: "paracheck" | "slither"
    check: str  # stable machine id: "hot-slot", "reentrancy-eth", ...
    severity: str  # one of SEVERITIES
    confidence: str  # "high" | "medium" | "low"
    title: str  # one line, human-readable
    description: str  # the full explanation
    contract: str | None = None
    file: str | None = None
    lines: list[int] = field(default_factory=list)
    suggested_fix: str | None = None
    # Evidence tier (see EVIDENCE_TIERS). Detectors that only pattern-match
    # default to "D": honest about the fact that nothing has been executed.
    # The proof engine is what promotes a finding to A/B, by attaching a PoC.
    evidence: str = "D"
    # For a proven finding, how to reproduce it: e.g.
    # {"poc_test": "test/PocH04.t.sol", "command": "forge test --match-path ...",
    #  "vulnerable": "PASS", "patched": "FAIL"}. Null for unproven findings.
    evidence_detail: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def proven(self) -> bool:
        return is_proven(self.evidence)

    @property
    def primary_line(self) -> int | None:
        return self.lines[0] if self.lines else None


def sort_findings(findings: list[Finding]) -> list[Finding]:
    """Proven first, then by severity, then by evidence, then stable.

    The top split is proven vs not: a proven medium (an exploit that
    reproduces) leads an unproven high (a lead), because acting on the thing
    that is real is the whole point of the product. *Within* each group,
    severity leads - among leads a high matters more than a medium - and
    evidence breaks ties, so a deterministic compatibility note sorts above a
    same-severity pattern hunch without ever jumping ahead of a more severe one.
    """
    confidence_rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(
        findings,
        key=lambda f: (
            0 if is_proven(f.evidence) else 1,
            severity_rank(f.severity),
            evidence_rank(f.evidence),
            confidence_rank.get(f.confidence, 3),
            f.check,
            f.primary_line or 0,
        ),
    )


def filter_findings(findings: list[Finding], min_severity: str = "info") -> list[Finding]:
    return [f for f in findings if at_least(f.severity, min_severity)]
