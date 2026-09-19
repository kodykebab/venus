"""Static-classifier correctness tests. Run these against the hand-written fixtures
(known-correct expected output) before trusting the classifier against the real
NaiveAMM/ShardedAMM contracts - the fixtures are the ground truth for the rules
themselves, the AMM contracts are regression coverage on top.

Requires `forge` on PATH (for the contracts/ Foundry project) and solc-select's active
compiler on PATH (for the single-file fixtures).
"""
import os

from report import analyze_contract

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
CONTRACTS_PROJECT = os.path.join(os.path.dirname(__file__), "..", "..", "contracts")


def test_global_counter_flagged_hot():
    report = analyze_contract(
        os.path.join(FIXTURES, "GlobalCounter.sol"),
        "GlobalCounter",
        os.path.join(FIXTURES, "GlobalCounter.sol"),
    )
    assert report["unanalyzable"] is False
    assert report["parallelismScore"] == 0
    slots = {f["slot"] for f in report["flags"]}
    assert slots == {"count"}
    assert report["flags"][0]["severity"] == "hot"
    assert set(report["flags"][0]["touchedBy"]) == {"increment", "incrementBy"}


def test_per_user_mapping_classified_safe():
    report = analyze_contract(
        os.path.join(FIXTURES, "PerUserMapping.sol"),
        "PerUserMapping",
        os.path.join(FIXTURES, "PerUserMapping.sol"),
    )
    assert report["unanalyzable"] is False
    assert report["parallelismScore"] == 100
    assert report["flags"] == []


def test_inline_assembly_is_unanalyzable_not_a_crash():
    report = analyze_contract(
        os.path.join(FIXTURES, "InlineAssemblyContract.sol"),
        "InlineAssemblyContract",
        os.path.join(FIXTURES, "InlineAssemblyContract.sol"),
    )
    assert report["unanalyzable"] is True
    assert report["parallelismScore"] is None
    assert report["flags"] == []
    assert "manual review recommended" in report["reason"]


def test_missing_contract_name_is_unanalyzable_not_a_crash():
    report = analyze_contract(
        os.path.join(FIXTURES, "GlobalCounter.sol"),
        "DoesNotExist",
        os.path.join(FIXTURES, "GlobalCounter.sol"),
    )
    assert report["unanalyzable"] is True
    assert "not found" in report["reason"]


def test_naive_amm_reserves_are_hot():
    report = analyze_contract(CONTRACTS_PROJECT, "NaiveAMM", os.path.join(CONTRACTS_PROJECT, "src", "NaiveAMM.sol"))
    assert report["unanalyzable"] is False
    assert report["parallelismScore"] == 0
    slots = {f["slot"]: f for f in report["flags"]}
    assert slots.keys() == {"reserve0", "reserve1"}
    for flag in slots.values():
        assert flag["severity"] == "hot"
        assert set(flag["touchedBy"]) == {"addLiquidity", "swap"}


def test_sharded_amm_swap_is_safe_addliquidity_is_hot():
    report = analyze_contract(
        CONTRACTS_PROJECT, "ShardedAMM", os.path.join(CONTRACTS_PROJECT, "src", "ShardedAMM.sol")
    )
    assert report["unanalyzable"] is False
    # swap() only indexes by a param-derived band -> not implicated in any flag.
    for flag in report["flags"]:
        assert "swap" not in flag["touchedBy"]
        assert flag["touchedBy"] == ["addLiquidity"]
    # ShardedAMM's swap-only safety must score strictly better than NaiveAMM's 0.
    assert report["parallelismScore"] > 0
