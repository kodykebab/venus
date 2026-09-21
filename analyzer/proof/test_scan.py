"""The scan-level proof orchestration: budget, class gating, in-place promotion,
and graceful no-op when proof is unavailable.
"""
import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static"))

from engine import Candidate  # noqa: E402
import scan as proof_scan  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "underflow")
HAS_FORGE = shutil.which("forge") is not None


@pytest.fixture
def repo():
    with tempfile.TemporaryDirectory() as tmp:
        dst = os.path.join(tmp, "underflow")
        shutil.copytree(FIXTURE, dst)
        yield dst


def _underflow_finding(check="integer-underflow", severity="high"):
    return {
        "source": "slither", "check": check, "severity": severity, "confidence": "high",
        "title": "Unchecked withdraw underflows", "description": "withdraw subtracts unchecked",
        "file": "src/Vault.sol", "lines": [16], "evidence": "D", "evidence_detail": None,
    }


def _good_generator(repo_dir):
    poc = open(os.path.join(FIXTURE, "test", "PocUnderflow.t.sol")).read()
    fix = open(os.path.join(FIXTURE, "patch", "Vault.sol")).read()

    def generate(finding, root):
        return Candidate("test/GenUnderflow.t.sol",
                         poc.replace("contract PocUnderflow", "contract GenUnderflow"),
                         "src/Vault.sol", fix)
    return generate


def test_no_key_and_no_generator_is_a_clean_noop(repo):
    findings = [_underflow_finding()]
    n = proof_scan.prove_findings(findings, repo, api_key=None)
    assert n == 0
    assert findings[0]["evidence"] == "D"  # untouched


def test_skips_findings_outside_the_provable_classes(repo):
    # A style nit is not something we spend a proof attempt on.
    findings = [_underflow_finding(check="naming-convention", severity="low")]
    called = {"n": 0}

    def gen(finding, root):
        called["n"] += 1
        return None

    n = proof_scan.prove_findings(findings, repo, api_key="k", generator=gen)
    assert n == 0 and called["n"] == 0, "generator must not be called for unprovable classes"


@pytest.mark.skipif(not HAS_FORGE, reason="forge not on PATH")
def test_promotes_a_provable_finding_in_place(repo):
    findings = [_underflow_finding()]
    n = proof_scan.prove_findings(findings, repo, api_key="k", generator=_good_generator(repo))
    assert n == 1
    assert findings[0]["evidence"] == "A"
    assert findings[0]["evidence_detail"]["vulnerable"] == "PASS"
    assert findings[0]["evidence_detail"]["patched"] == "FAIL"


@pytest.mark.skipif(not HAS_FORGE, reason="forge not on PATH")
def test_respects_the_attempt_budget(repo):
    findings = [_underflow_finding() for _ in range(4)]
    calls = {"n": 0}
    good = _good_generator(repo)

    def counting(finding, root):
        calls["n"] += 1
        return good(finding, root)

    proof_scan.prove_findings(findings, repo, api_key="k", generator=counting, max_attempts=2)
    assert calls["n"] == 2, "must not attempt more findings than the budget allows"
