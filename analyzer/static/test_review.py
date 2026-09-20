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


def test_llm_layer_calls_messages_parse_with_injected_client():
    import synthesize

    class FakeMessages:
        def __init__(self):
            self.arguments = None

        def parse(self, **kwargs):
            self.arguments = kwargs
            return type("Response", (), {
                "stop_reason": "end_turn",
                "parsed_output": "parsed review",
            })()

    class FakeClient:
        def __init__(self):
            self.messages = FakeMessages()

    client = FakeClient()
    result = synthesize.synthesize_review(
        {"findings": [{"check": "hot-slot"}]},
        diff="diff --git a/A.sol b/A.sol",
        source="contract A {}",
        model="test-model",
        client=client,
        api_key="test-key",
    )

    assert result == "parsed review"
    assert client.messages.arguments["model"] == "test-model"
    assert client.messages.arguments["output_format"] is synthesize.SynthesizedReview
    assert "hot-slot" in client.messages.arguments["messages"][0]["content"]
    assert "contract A {}" in client.messages.arguments["messages"][0]["content"]


# --- project mode -----------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONTRACTS_PROJECT = os.path.join(REPO_ROOT, "contracts")


def test_detects_the_build_system():
    from project import detect_project

    foundry = detect_project(CONTRACTS_PROJECT)
    assert foundry.framework == "foundry"
    assert foundry.source_dir == "src"
    assert foundry.is_installable

    assert detect_project(FIXTURES).framework == "plain"


def test_project_review_resolves_imports_and_skips_dependencies():
    from review import review_project

    report = review_project(CONTRACTS_PROJECT)
    assert report["unanalyzable"] is False
    assert report["project"]["framework"] == "foundry"

    names = {c["contract"] for c in report["contracts"]}
    # First-party contracts - these import ./interfaces/*, which the single-file
    # path cannot resolve at all.
    assert {"NaiveAMM", "ShardedAMM", "DemoToken"} <= names
    # forge-std compiles alongside them and must not be reviewed.
    assert not any(n.startswith("Std") or n == "Vm" for n in names)
    assert all("lib/" not in (f["file"] or "") for f in report["findings"])


def test_project_review_scopes_output_to_changed_files():
    from review import review_project

    scoped = review_project(CONTRACTS_PROJECT, changed_files=["contracts/src/NaiveAMM.sol"])
    assert {c["contract"] for c in scoped["contracts"]} == {"NaiveAMM"}
    assert {f["file"] for f in scoped["findings"]} == {"contracts/src/NaiveAMM.sol"}
    # Whole-project analysis still ran - NaiveAMM's score reflects its full contract.
    assert scoped["contracts"][0]["parallelismScore"] == 0


# --- multi-chain ------------------------------------------------------------

def test_chain_resolution_by_key_and_id():
    from chains import resolve_chain

    assert resolve_chain("monad").parallel_execution is True
    assert resolve_chain(10143).name == "Monad Testnet"
    assert resolve_chain("ethereum").parallel_execution is False
    assert resolve_chain(1).key == "ethereum"
    # An unknown chain must not claim an execution model it doesn't know.
    assert resolve_chain("some-new-l2").parallel_execution is False
    assert resolve_chain(None).key == "monad", "defaults to Monad"


def test_parallelism_only_runs_on_parallel_chains():
    on_monad = review_file(VULNERABLE, chain="monad")
    on_ethereum = review_file(VULNERABLE, chain="ethereum")

    assert on_monad["chain"]["parallelismAnalysisRan"] is True
    assert any(f["check"] == "hot-slot" for f in on_monad["findings"])
    assert on_monad["contracts"][0]["parallelismScore"] is not None

    # Contended slots are meaningless where execution is sequential - reporting
    # them would be noise dressed up as a finding.
    assert on_ethereum["chain"]["parallelismAnalysisRan"] is False
    assert not any(f["check"] == "hot-slot" for f in on_ethereum["findings"])
    assert on_ethereum["contracts"][0]["parallelismScore"] is None


def test_universal_checks_run_on_every_chain():
    monad_checks = {f["check"] for f in review_file(VULNERABLE, chain="monad")["findings"]}
    eth_checks = {f["check"] for f in review_file(VULNERABLE, chain="ethereum")["findings"]}
    # Everything Slither finds is execution-model independent.
    assert "arbitrary-send-eth" in monad_checks and "arbitrary-send-eth" in eth_checks
    assert monad_checks - eth_checks == {"hot-slot"}


def test_render_explains_a_skipped_parallelism_pass():
    rendered = render_markdown(review_file(VULNERABLE, chain="ethereum"), "x.sol")
    assert "Ethereum" in rendered
    assert "parallelism analysis was skipped" in rendered
    assert "Safe under concurrency" not in rendered
