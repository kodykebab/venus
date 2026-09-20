"""Tests for the unified review pipeline: schema, detector normalization, the
merged report, Markdown rendering, and the LLM layer's graceful degradation.

Requires `forge` and solc-select's active compiler on PATH, same as
test_classifier.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "llm"))

from render import render_markdown
from review import review_file
from schema import Finding, at_least, filter_findings, severity_from_slither_impact, sort_findings

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
VULNERABLE = os.path.join(FIXTURES, "VulnerableSample.sol")
STAKING = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "contracts", "samples", "StakingPoolSample.sol",
)


def test_severity_ordering_and_filtering():
    findings = [
        Finding("slither", "low-one", "low", "high", "t", "d"),
        Finding("paracheck", "hot", "high", "medium", "t", "d"),
        Finding("slither", "noise", "info", "low", "t", "d"),
    ]
    assert [f.check for f in sort_findings(findings)] == ["hot", "low-one", "noise"]
    assert [f.check for f in filter_findings(findings, "low")] == ["low-one", "hot"]
    assert at_least("high", "medium") and not at_least("low", "high")


def test_slither_impact_maps_onto_our_scale():
    assert severity_from_slither_impact("High") == "high"
    assert severity_from_slither_impact("Optimization") == "optimization"
    assert severity_from_slither_impact("something-unknown") == "info"


def test_review_merges_both_analyzers():
    report = review_file(VULNERABLE)
    assert report["unanalyzable"] is False

    sources = {f["source"] for f in report["findings"]}
    assert sources == {"paracheck", "slither"}, "both analyzers must contribute findings"

    # The deliberately arbitrary `drain()` send is the headline finding.
    assert report["findings"][0]["severity"] == "high"
    assert report["findings"][0]["check"] == "arbitrary-send-eth"

    # The shared `total` counter is ParaCheck's own category.
    hot = [f for f in report["findings"] if f["check"] == "hot-slot"]
    assert hot and hot[0]["contract"] == "Vulnerable"
    assert hot[0]["lines"], "hot-slot findings need a line number for inline annotations"


def test_findings_are_reported_under_the_requested_path():
    report = review_file(VULNERABLE)
    assert all(f["file"] == VULNERABLE for f in report["findings"])


def test_min_severity_filters_the_report():
    everything = review_file(VULNERABLE, min_severity="info")
    serious = review_file(VULNERABLE, min_severity="high")
    assert len(serious["findings"]) < len(everything["findings"])
    assert all(f["severity"] == "high" for f in serious["findings"])


def test_unanalyzable_file_never_raises():
    report = review_file(os.path.join(FIXTURES, "InlineAssemblyContract.sol"))
    assert report["unanalyzable"] is True
    assert "manual review recommended" in report["reason"]
    assert report["findings"] == []


def test_render_markdown_covers_both_states():
    rendered = render_markdown(review_file(STAKING), "StakingPoolSample.sol")
    assert "parallelism score" in rendered
    assert "hot-slot" in rendered

    bad = render_markdown({"unanalyzable": True, "reason": "nope"}, "x.sol")
    assert "Unanalyzable" in bad and "nope" in bad


def test_llm_layer_degrades_without_credentials(monkeypatch):
    import synthesize

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    assert synthesize.credentials_available() is False
    # No key must be a soft failure - CI still gets a review from raw findings.
    assert synthesize.synthesize_review(review_file(STAKING)) is None
    assert synthesize.synthesize_review({"unanalyzable": True}) is None
