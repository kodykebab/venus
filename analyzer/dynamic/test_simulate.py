"""Tests for the fork-based dynamic simulator.

These actually spin up anvil, deploy, and trace, so they're slower than the
static tests - but the whole claim of this layer is that it measures rather
than infers, and a mocked version of that would test nothing.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static"))

from simulate import Call, SimulationSpec, simulate  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STAKING = os.path.join(REPO_ROOT, "contracts", "samples", "StakingPoolSample.sol")


def test_spec_parses_a_declared_simulation():
    spec = SimulationSpec.from_dict({
        "contract": "Foo",
        "constructorArgs": [1, "0xabc"],
        "setup": [{"signature": "init()", "value": 5}],
        "concurrent": {"signature": "go(uint256)", "args": [7]},
        "senders": 3,
    })
    assert spec.contract == "Foo"
    assert spec.constructor_args == ["1", "0xabc"]
    assert spec.setup[0].value == "5"
    assert spec.concurrent.args == ["7"]
    assert spec.senders == 3


def test_simulation_without_a_concurrent_call_is_skipped_not_failed():
    result = simulate(STAKING, SimulationSpec(contract="StakingPoolSample"))
    assert result["ran"] is False
    assert "No concurrent call" in result["reason"]


def test_missing_contract_reports_why():
    spec = SimulationSpec(contract="NotInThisFile", concurrent=Call("stake()"))
    result = simulate(STAKING, spec)
    assert result["ran"] is False
    # "couldn't measure" must never look like "measured zero conflicts"
    assert "not found" in result["reason"]


@pytest.mark.slow
def test_measures_real_contention_on_an_undeployed_contract():
    spec = SimulationSpec(
        contract="StakingPoolSample",
        concurrent=Call("stake()", value="1000000000000000000"),
        senders=5,
    )
    result = simulate(STAKING, spec)

    assert result["ran"] is True, result.get("reason")
    # All five had to land in one block - conflicts can't happen across blocks.
    assert result["transactionsInBlock"] == 5
    # totalStaked is written by every stake() call.
    assert result["conflictingSlots"] == 1
    # C(5,2) - every pair of the five collides.
    assert result["conflictingTransactionPairs"] == 10


@pytest.mark.slow
def test_confirmed_findings_name_the_variable():
    from slither import Slither

    from dynamic_review import simulation_findings

    spec = SimulationSpec(
        contract="StakingPoolSample",
        concurrent=Call("stake()", value="1000000000000000000"),
        senders=5,
    )
    result = simulate(STAKING, spec)
    assert result["ran"] is True, result.get("reason")

    contract = next(c for c in Slither(STAKING).contracts if c.name == "StakingPoolSample")
    findings = simulation_findings(contract, result, STAKING)

    assert len(findings) == 1
    finding = findings[0]
    # Measured evidence outranks the static prediction of the same slot.
    assert finding.severity == "high" and finding.confidence == "high"
    assert finding.check == "hot-slot-confirmed"
    assert "totalStaked" in finding.title
    assert finding.lines == [18], "must point at the declaration for inline annotation"
