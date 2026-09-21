"""The real proof generator: asks Claude for a Foundry PoC and a candidate fix.

This is the only place a model is trusted to *write* anything, and it is trusted
with nothing. Whatever it returns is handed straight to the validator, which
runs it. A confident-but-wrong PoC fails the polarity flip and the finding stays
unproven; a PoC that does not compile is an ERROR and stays unproven. The model
proposes; `forge test` disposes.

Kept behind a factory so the engine stays model-agnostic and unit-testable with
a canned generator (see test_proof.py). The SDK is imported lazily so the
analyzers still run with no credentials and no `anthropic` installed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static"))

from schema import Finding  # noqa: E402

from engine import Candidate  # noqa: E402

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """You write proof-of-concept exploits for EVM smart contract \
vulnerabilities, as Foundry tests.

You are given one finding and the full source of the file it is in. Produce two \
things:

1. A single self-contained Foundry test (Solidity) that demonstrates the bug. The \
test function must PASS when run against the current (vulnerable) code, by \
asserting the attacker actually achieved something they should not have been able \
to (funds moved, state corrupted, a guard bypassed). Use only forge-std (`import \
"forge-std/Test.sol";`) and the contract under test. Deploy the contract in the \
test itself; do not assume any external fixture.

2. A fixed version of the SAME source file: the complete file contents with the \
vulnerability corrected, changing as little else as possible. The fix must make \
your PoC's key assertion FAIL (by reverting or by preventing the attacker's gain).

The whole point is that your test flips: it passes on the vulnerable code and \
fails on your fix. If you cannot construct a test that genuinely depends on the \
bug, say so by returning an empty poc_source rather than a test that would pass \
regardless. A test that passes on both versions is worse than nothing.

Write real, compiling Solidity. No placeholders, no `// ...`, no TODO."""


class GeneratedProof(BaseModel):
    can_prove: bool = Field(
        description="False if you cannot build a PoC that genuinely depends on this bug."
    )
    poc_contract_name: str = Field(
        description="A valid Solidity identifier for the test contract, e.g. ReentrancyPoC."
    )
    poc_source: str = Field(
        description="The complete Foundry test file. Empty string if can_prove is false."
    )
    fixed_source: str = Field(
        description="The complete corrected contents of the target file. Empty if can_prove is false."
    )
    explanation: str = Field(
        description="One or two sentences on how the exploit works."
    )


def _prompt(finding: Finding, source: str) -> str:
    loc = f"{finding.file}" + (f":{finding.lines[0]}" if finding.lines else "")
    return (
        f"## Finding\n\n"
        f"- Title: {finding.title}\n"
        f"- Check: {finding.check}\n"
        f"- Severity: {finding.severity}\n"
        f"- Location: {loc}\n"
        f"- Contract: {finding.contract or 'unknown'}\n\n"
        f"### Description\n\n{finding.description}\n\n"
        f"## Full source of {finding.file}\n\n"
        f"```solidity\n{source.strip()}\n```\n\n"
        f"Write the PoC and the fix."
    )


def claude_generator(api_key: str | None = None, model: str = MODEL, client=None):
    """Build a Generator (Finding, repo -> Candidate | None) backed by Claude."""

    def generate(finding: Finding, repo: Path) -> Candidate | None:
        if not finding.file:
            return None
        target = Path(repo) / finding.file
        try:
            source = target.read_text()
        except OSError:
            return None

        nonlocal client
        import anthropic  # lazy: analyzers run without the SDK

        if client is None:
            client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

        try:
            response = client.messages.parse(
                model=model,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                system=[{
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": _prompt(finding, source)}],
                output_format=GeneratedProof,
            )
        except anthropic.APIError as exc:
            print(f"paracheck: proof generation failed ({exc.__class__.__name__}) - leaving unproven.")
            return None

        proof = response.parsed
        if proof is None or not proof.can_prove or not proof.poc_source.strip():
            return None

        name = "".join(c for c in proof.poc_contract_name if c.isalnum()) or "GeneratedPoC"
        return Candidate(
            poc_filename=f"test/Paracheck_{name}.t.sol",
            poc_source=proof.poc_source,
            fix_target=finding.file,
            fixed_source=proof.fixed_source,
        )

    return generate
