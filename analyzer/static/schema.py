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

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def primary_line(self) -> int | None:
        return self.lines[0] if self.lines else None


def sort_findings(findings: list[Finding]) -> list[Finding]:
    """Most severe first, then highest confidence, then stable by check name."""
    confidence_rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(
        findings,
        key=lambda f: (
            severity_rank(f.severity),
            confidence_rank.get(f.confidence, 3),
            f.check,
            f.primary_line or 0,
        ),
    )


def filter_findings(findings: list[Finding], min_severity: str = "info") -> list[Finding]:
    return [f for f in findings if at_least(f.severity, min_severity)]
