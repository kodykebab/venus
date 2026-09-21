"""The Claude-backed generator, tested with an injected fake client so it needs
no key and no network. The end-to-end generate->validate->promote path is
covered by test_proof.py with a real forge; here we only pin the prompt
assembly and the GeneratedProof -> Candidate mapping.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static"))

from schema import Finding  # noqa: E402

import generate  # noqa: E402
from generate import GeneratedProof, claude_generator  # noqa: E402


class _FakeMessages:
    def __init__(self, proof):
        self._proof = proof
        self.arguments = None

    def parse(self, **kwargs):
        self.arguments = kwargs
        return type("Response", (), {"parsed": self._proof})()


class _FakeClient:
    def __init__(self, proof):
        self.messages = _FakeMessages(proof)


def _finding():
    return Finding(
        source="paracheck", check="reentrancy-eth", severity="high", confidence="high",
        title="Reentrancy in withdraw", description="external call before state update",
        contract="Vault", file="src/Vault.sol", lines=[42],
    )


def test_maps_a_generated_proof_onto_a_candidate(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Vault.sol").write_text("contract Vault { }")

    proof = GeneratedProof(
        can_prove=True,
        poc_contract_name="ReentrancyPoC",
        poc_source="contract ReentrancyPoC { }",
        fixed_source="contract Vault { /* fixed */ }",
        explanation="reenters withdraw",
    )
    client = _FakeClient(proof)
    gen = claude_generator(client=client)

    candidate = gen(_finding(), tmp_path)
    assert candidate is not None
    assert candidate.poc_filename == "test/Paracheck_ReentrancyPoC.t.sol"
    assert candidate.fix_target == "src/Vault.sol"
    assert candidate.fixed_source == "contract Vault { /* fixed */ }"

    # The prompt carried the finding and the real source of the target file.
    content = client.messages.arguments["messages"][0]["content"]
    assert "Reentrancy in withdraw" in content
    assert "src/Vault.sol:42" in content
    assert "contract Vault { }" in content
    assert client.messages.arguments["output_format"] is GeneratedProof


def test_returns_none_when_the_model_cannot_prove_it(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Vault.sol").write_text("contract Vault { }")

    proof = GeneratedProof(can_prove=False, poc_contract_name="", poc_source="",
                           fixed_source="", explanation="too complex to shape into an exploit")
    gen = claude_generator(client=_FakeClient(proof))
    assert gen(_finding(), tmp_path) is None


def test_returns_none_when_the_target_file_is_missing(tmp_path):
    gen = claude_generator(client=_FakeClient(None))
    # finding.file points nowhere under tmp_path -> no source to read.
    assert gen(_finding(), tmp_path) is None
