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


# --- spec validation --------------------------------------------------------
#
# A simulation spec arrives in the repository under review, so it is hostile
# input. There's no shell involved (every subprocess takes an argv list), but a
# value starting with "-" would be read by `cast` as an option rather than a
# positional - which would let a repo point `cast send` at an RPC and key of its
# choosing. These cases must stay blocked.

import pytest as _pytest  # noqa: E402

from simulate import SpecValidationError  # noqa: E402


@_pytest.mark.parametrize(
    "description,spec",
    [
        ("signature is an option", {"contract": "A", "concurrent": {"signature": "--rpc-url"}}),
        ("argument is an option",
         {"contract": "A", "concurrent": {"signature": "go(uint256)", "args": ["--private-key"]}}),
        ("contract name is an option", {"contract": "--help", "concurrent": {"signature": "go()"}}),
        ("signature carries a payload",
         {"contract": "A", "concurrent": {"signature": "go(); rm -rf /"}}),
        ("fork url reads a local file",
         {"contract": "A", "concurrent": {"signature": "go()"}, "forkUrl": "file:///etc/passwd"}),
        ("fork url is an option",
         {"contract": "A", "concurrent": {"signature": "go()"}, "forkUrl": "--foo"}),
        ("sender count is unbounded",
         {"contract": "A", "concurrent": {"signature": "go()"}, "senders": 9999}),
        ("value smuggles an option",
         {"contract": "A", "concurrent": {"signature": "go()", "value": "1 --x"}}),
    ],
)
def test_hostile_specs_are_rejected(description, spec):
    with _pytest.raises(SpecValidationError):
        SimulationSpec.from_dict(spec)


def test_a_legitimate_spec_still_parses():
    spec = SimulationSpec.from_dict({
        "contract": "StakingPoolSample",
        "concurrent": {"signature": "stake()", "value": "1000000000000000000"},
        "senders": 5,
    })
    assert spec.contract == "StakingPoolSample"
    assert spec.senders == 5


def test_rejected_spec_surfaces_as_a_reason_not_a_crash():
    from simulate import simulate as run

    # Spec validation happens at construction, so callers building one from
    # untrusted JSON get an exception; simulate() itself never leaks a traceback.
    result = run(STAKING, SimulationSpec(contract="Nope", concurrent=Call("stake()")))
    assert result["ran"] is False and "reason" in result
