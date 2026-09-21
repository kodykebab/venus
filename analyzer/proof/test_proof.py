"""The proof engine and validator, exercised against a self-contained Foundry
fixture (analyzer/proof/fixtures/underflow).

These are the tests that guard the core promise: a PoC is trusted only if it
flips polarity, and a finding is promoted to tier A only through that gate.
They need `forge` on PATH and are skipped otherwise, like the other
forge-dependent tests in this repo.
"""
import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static"))

from schema import Finding  # noqa: E402

from engine import Candidate, prove_finding  # noqa: E402
from validate import Verdict, validate_poc  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "underflow")

pytestmark = pytest.mark.skipif(shutil.which("forge") is None, reason="forge not on PATH")


@pytest.fixture
def repo():
    """A throwaway copy of the fixture so the patch swap never touches source."""
    with tempfile.TemporaryDirectory() as tmp:
        dst = os.path.join(tmp, "underflow")
        shutil.copytree(FIXTURE, dst)
        yield dst


def _fix_source(repo_dir: str) -> str:
    return open(os.path.join(repo_dir, "patch", "Vault.sol")).read()


def test_validator_confirms_a_pinned_poc(repo):
    result = validate_poc(repo, "test/PocUnderflow.t.sol", os.path.join(repo, "patch", "Vault.sol"),
                          "src/Vault.sol")
    assert result.verdict is Verdict.VALIDATED
    assert result.vulnerable == "PASS" and result.patched == "FAIL"


def test_validator_rejects_a_poc_that_is_not_pinned(repo):
    # PocNotPinned passes regardless of the fix, so it must not validate.
    result = validate_poc(repo, "test/PocNotPinned.t.sol", os.path.join(repo, "patch", "Vault.sol"),
                          "src/Vault.sol")
    assert result.verdict is Verdict.NOT_PINNED


def test_validator_restores_the_source_afterwards(repo):
    before = open(os.path.join(repo, "src", "Vault.sol")).read()
    validate_poc(repo, "test/PocUnderflow.t.sol", os.path.join(repo, "patch", "Vault.sol"),
                 "src/Vault.sol")
    after = open(os.path.join(repo, "src", "Vault.sol")).read()
    assert before == after, "the vulnerable source must be restored after validation"


def _finding() -> Finding:
    return Finding(
        source="paracheck", check="int-underflow", severity="high", confidence="high",
        title="Unchecked withdraw underflows balance", description="withdraw subtracts unchecked",
        file="src/Vault.sol",
    )


def test_engine_promotes_a_finding_when_the_poc_flips(repo):
    poc = open(os.path.join(FIXTURE, "test", "PocUnderflow.t.sol")).read()

    def generator(finding, root):
        return Candidate(
            poc_filename="test/GenPoc.t.sol",
            poc_source=poc.replace("contract PocUnderflow", "contract GenPoc"),
            fix_target="src/Vault.sol",
            fixed_source=_fix_source(repo),
        )

    outcome = prove_finding(_finding(), repo, generator)
    assert outcome.promoted
    assert outcome.finding.evidence == "A"
    assert outcome.finding.proven
    detail = outcome.finding.evidence_detail
    assert detail["vulnerable"] == "PASS" and detail["patched"] == "FAIL"
    assert detail["command"] == "forge test --match-path test/GenPoc.t.sol"
    # The PoC that earned tier A stays on disk so the printed command runs.
    assert os.path.exists(os.path.join(repo, "test", "GenPoc.t.sol"))


def test_engine_leaves_finding_unproven_when_poc_is_not_pinned(repo):
    notpinned = open(os.path.join(FIXTURE, "test", "PocNotPinned.t.sol")).read()

    def generator(finding, root):
        return Candidate(
            poc_filename="test/GenNotPinned.t.sol",
            poc_source=notpinned.replace("contract PocNotPinned", "contract GenNotPinned"),
            fix_target="src/Vault.sol",
            fixed_source=_fix_source(repo),
        )

    outcome = prove_finding(_finding(), repo, generator)
    assert not outcome.promoted
    assert outcome.finding.evidence == "D"
    assert "not_pinned" in outcome.reason
    # A PoC that did not earn its tier is cleaned up, not left lying around.
    assert not os.path.exists(os.path.join(repo, "test", "GenNotPinned.t.sol"))


def test_engine_survives_a_noncompiling_poc(repo):
    def generator(finding, root):
        return Candidate(
            poc_filename="test/GenBroken.t.sol",
            poc_source="this is not valid solidity",
            fix_target="src/Vault.sol",
            fixed_source=_fix_source(repo),
        )

    outcome = prove_finding(_finding(), repo, generator)
    assert not outcome.promoted
    assert outcome.finding.evidence == "D"


def test_engine_handles_a_generator_with_nothing_to_offer(repo):
    outcome = prove_finding(_finding(), repo, lambda finding, root: None)
    assert not outcome.promoted
    assert "no candidate" in outcome.reason
