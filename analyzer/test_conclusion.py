"""The check-run blocking gate: only proven findings may fail a check.

This is the load-bearing precision guarantee - an unproven pattern match never
breaks a developer's build, however severe it looks. If this test ever goes
green while conclusion_for lets unproven findings block, the product has
quietly become the noisy scanner it exists to replace.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import conclusion_for


def _finding(severity: str, evidence: str) -> dict:
    return {"severity": severity, "evidence": evidence, "check": "x"}


def test_unproven_findings_never_block_even_when_severe():
    findings = [_finding("critical", "D"), _finding("high", "C")]
    assert conclusion_for(findings, "high") == "success"


def test_proven_finding_at_threshold_blocks():
    findings = [_finding("high", "A")]
    assert conclusion_for(findings, "high") == "failure"


def test_proven_finding_below_threshold_does_not_block():
    findings = [_finding("medium", "A")]
    assert conclusion_for(findings, "high") == "success"


def test_symbolic_counterexample_also_blocks():
    findings = [_finding("critical", "B")]
    assert conclusion_for(findings, "critical") == "failure"


def test_proven_and_unproven_mixed_blocks_only_on_the_proven_one():
    findings = [_finding("critical", "D"), _finding("high", "A")]
    assert conclusion_for(findings, "high") == "failure"
    # Raise the bar above the proven finding: the unproven critical still
    # cannot rescue a block into existence.
    assert conclusion_for(findings, "critical") == "success"


def test_no_threshold_never_fails():
    assert conclusion_for([], None) == "success"
    assert conclusion_for([_finding("critical", "A")], None) == "neutral"


def test_unknown_fail_on_is_neutral():
    assert conclusion_for([_finding("high", "A")], "not-a-severity") == "neutral"
