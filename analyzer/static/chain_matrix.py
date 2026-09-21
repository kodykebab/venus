"""Chain Matrix: will this contract behave the same on every chain I ship to?

A large share of real cross-chain incidents are not exploits at all - they are
the same bytecode doing something different on another chain. `.transfer()`'s
2300-gas stipend that works on Ethereum and reverts on zkSync Era; `block.number`
that means an L1 block on Arbitrum, so block-count timing is wrong; PUSH0 emitted
by a recent compiler and rejected by a chain that never adopted it.

These are deterministic facts about the code and the target chain, not heuristic
guesses, so the matrix is almost never wrong - which is exactly why it is a good
first thing to show a developer who has learned to ignore scanners. Nothing here
is an exploit, so nothing here blocks a merge: every finding is evidence tier C,
information the developer acts on before they ship, not a gate.

Pure and source-level: give it the flattened source, the compiler settings, and
the chains to check. No forge, no network. The probe fleet that measures these
facts against live chains rather than asserting them is the next step; this is
the table it will keep honest.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChainFacts:
    key: str
    name: str
    # Opcode / semantic capabilities that differ across EVM chains.
    push0: bool = True  # accepts the PUSH0 opcode (Shanghai)
    fixed_gas_transfer_ok: bool = True  # 2300-gas .transfer()/.send() is safe
    selfdestruct: str = "normal"  # "normal" | "deprecated" | "altered"
    block_number: str = "l2"  # "l2" (own block) | "l1_slow" (Arbitrum: L1 number)
    block_randomness: str = "prevrandao"  # "prevrandao" | "altered" | "zero"
    tx_origin_eoa: bool = True  # tx.origin == msg.sender reliably means an EOA
    create2_standard: bool = True  # standard CREATE2 address derivation


# The deploy set worth checking. Facts drawn from each chain's own docs and the
# community multichain-auditor reference; the probe fleet will supersede this.
CHAIN_FACTS: dict[str, ChainFacts] = {
    "ethereum": ChainFacts("ethereum", "Ethereum"),
    "monad": ChainFacts("monad", "Monad"),
    "base": ChainFacts("base", "Base"),
    "arbitrum": ChainFacts(
        "arbitrum", "Arbitrum One",
        block_number="l1_slow", block_randomness="altered", tx_origin_eoa=False,
    ),
    "optimism": ChainFacts(
        "optimism", "OP Mainnet",
        block_randomness="altered", tx_origin_eoa=False,
    ),
    "polygon": ChainFacts("polygon", "Polygon PoS"),
    "bsc": ChainFacts("bsc", "BNB Smart Chain"),
    "zksync-era": ChainFacts(
        "zksync-era", "zkSync Era",
        push0=False, fixed_gas_transfer_ok=False, selfdestruct="altered", create2_standard=False,
    ),
    "linea": ChainFacts("linea", "Linea"),
    "scroll": ChainFacts("scroll", "Scroll"),
    "sei": ChainFacts("sei", "Sei"),
    "megaeth": ChainFacts("megaeth", "MegaETH"),
}

DEFAULT_MATRIX_CHAINS = [
    "ethereum", "monad", "base", "arbitrum", "optimism", "zksync-era",
]


@dataclass
class MatrixCheck:
    id: str
    title: str
    # A source detector: returns the 1-based line numbers where it fires.
    detect: "callable"
    # (facts) -> ("ok" | "warn" | "incompatible", reason) for a chain.
    verdict: "callable"
    fix: str = ""


Cell = str  # "ok" | "warn" | "incompatible" | "na"


def _lines_matching(source: str, pattern: re.Pattern) -> list[int]:
    return [i for i, line in enumerate(source.splitlines(), start=1)
            if pattern.search(_strip_comment(line))]


def _strip_comment(line: str) -> str:
    # Cheap single-line comment strip so a `// selfdestruct` mention doesn't
    # fire. Not a full parser; block comments and strings are out of scope for
    # v1, and a false positive here is a warning, not a broken build.
    idx = line.find("//")
    return line[:idx] if idx != -1 else line


_RE_TRANSFER = re.compile(r"\.(transfer|send)\s*\(")
_RE_SELFDESTRUCT = re.compile(r"\b(selfdestruct|suicide)\s*\(")
_RE_BLOCK_NUMBER = re.compile(r"\bblock\.number\b")
_RE_RANDOMNESS = re.compile(r"\bblock\.(difficulty|prevrandao)\b")
_RE_TX_ORIGIN = re.compile(r"\btx\.origin\b")


def _push0_lines(source: str, solc_version: str | None, evm_version: str | None) -> list[int]:
    """PUSH0 is a compiler-settings fact, not a source construct: solc >= 0.8.20
    emits it unless evm_version is pinned below Shanghai. We attribute it to the
    pragma line so the developer has somewhere to look."""
    if evm_version and evm_version.lower() in {
        "paris", "london", "berlin", "istanbul", "petersburg", "constantinople", "byzantium"
    }:
        return []
    version = solc_version or _pragma_version(source)
    if version and _at_least_0_8_20(version):
        for i, line in enumerate(source.splitlines(), start=1):
            if "pragma solidity" in line:
                return [i]
        return [1]
    return []


def _pragma_version(source: str) -> str | None:
    m = re.search(r"pragma\s+solidity\s+[^\d]*(\d+\.\d+\.\d+)", source)
    return m.group(1) if m else None


def _at_least_0_8_20(version: str) -> bool:
    try:
        major, minor, patch = (int(p) for p in version.split(".")[:3])
    except ValueError:
        return False
    return (major, minor, patch) >= (0, 8, 20)


CHECKS: list[MatrixCheck] = [
    MatrixCheck(
        "push0",
        "PUSH0 opcode emitted by the compiler",
        detect=lambda src, solc, evm: _push0_lines(src, solc, evm),
        verdict=lambda f: ("ok", "") if f.push0 else
                          ("incompatible", f"{f.name} rejects PUSH0; pin evm_version to paris or below"),
        fix="Set evm_version to \"paris\" in foundry.toml / hardhat config to stop the compiler emitting PUSH0.",
    ),
    MatrixCheck(
        "fixed-gas-transfer",
        "Fixed 2300-gas .transfer() / .send()",
        detect=lambda src, solc, evm: _lines_matching(src, _RE_TRANSFER),
        verdict=lambda f: ("ok", "") if f.fixed_gas_transfer_ok else
                          ("incompatible", f"{f.name} can revert on a 2300-gas stipend; use call{{value:...}}"),
        fix="Replace .transfer()/.send() with (bool ok,) = payable(x).call{value: amount}(\"\"); require(ok);",
    ),
    MatrixCheck(
        "selfdestruct",
        "selfdestruct used",
        detect=lambda src, solc, evm: _lines_matching(src, _RE_SELFDESTRUCT),
        verdict=lambda f: ("ok", "") if f.selfdestruct == "normal" else
                          ("incompatible" if f.selfdestruct == "altered" else "warn",
                           f"{f.name} handles selfdestruct differently ({f.selfdestruct})"),
        fix="Avoid selfdestruct; its semantics diverge across chains and are deprecated on Ethereum.",
    ),
    MatrixCheck(
        "block-number-timing",
        "block.number used (often for timing)",
        detect=lambda src, solc, evm: _lines_matching(src, _RE_BLOCK_NUMBER),
        verdict=lambda f: ("ok", "") if f.block_number == "l2" else
                          ("warn", f"{f.name}'s block.number is the L1 number and updates ~1/min; "
                                   f"block-count timing will be wrong"),
        fix="Use block.timestamp for time, or Arbitrum's arbBlockNumber() for the real L2 block.",
    ),
    MatrixCheck(
        "block-randomness",
        "block.difficulty / block.prevrandao used",
        detect=lambda src, solc, evm: _lines_matching(src, _RE_RANDOMNESS),
        verdict=lambda f: ("ok", "") if f.block_randomness == "prevrandao" else
                          ("warn", f"{f.name} does not provide meaningful prevrandao; value may be constant"),
        fix="Do not use block randomness as an entropy source on L2s; use a VRF.",
    ),
    MatrixCheck(
        "tx-origin-eoa",
        "tx.origin used (often as an EOA check)",
        detect=lambda src, solc, evm: _lines_matching(src, _RE_TX_ORIGIN),
        verdict=lambda f: ("ok", "") if f.tx_origin_eoa else
                          ("warn", f"on {f.name}, tx.origin == msg.sender can be true for a contract call"),
        fix="Do not rely on tx.origin == msg.sender to prove the caller is an EOA on L2s.",
    ),
]


@dataclass
class MatrixRow:
    check_id: str
    title: str
    lines: list[int]
    cells: dict[str, Cell]  # chain key -> verdict
    fix: str = ""
    reasons: dict[str, str] = field(default_factory=dict)  # chain key -> reason


def build_matrix(
    source: str,
    chains: list[str] | None = None,
    *,
    solc_version: str | None = None,
    evm_version: str | None = None,
) -> list[MatrixRow]:
    """The matrix: one row per construct actually present in the source, one
    column per target chain. Rows for constructs the code does not use are
    omitted - an empty cell is noise, and the point is precision."""
    chain_keys = chains or DEFAULT_MATRIX_CHAINS
    facts = [CHAIN_FACTS[k] for k in chain_keys if k in CHAIN_FACTS]

    rows: list[MatrixRow] = []
    for check in CHECKS:
        lines = check.detect(source, solc_version, evm_version)
        if not lines:
            continue
        cells: dict[str, Cell] = {}
        reasons: dict[str, str] = {}
        for f in facts:
            verdict, reason = check.verdict(f)
            cells[f.key] = verdict
            if reason:
                reasons[f.key] = reason
        rows.append(MatrixRow(check.id, check.title, lines, cells, check.fix, reasons))
    return rows


def matrix_to_dict(rows: list[MatrixRow], chains: list[str] | None = None) -> dict:
    chain_keys = chains or DEFAULT_MATRIX_CHAINS
    return {
        "chains": [{"key": k, "name": CHAIN_FACTS[k].name} for k in chain_keys if k in CHAIN_FACTS],
        "rows": [
            {
                "check": r.check_id,
                "title": r.title,
                "lines": r.lines,
                "cells": r.cells,
                "reasons": r.reasons,
                "fix": r.fix,
            }
            for r in rows
        ],
    }


def matrix_findings(
    source: str,
    file: str,
    *,
    chains: list[str] | None = None,
    solc_version: str | None = None,
    evm_version: str | None = None,
) -> list[dict]:
    """Emit one finding per construct that is incompatible or risky on at least
    one target chain, so the matrix flows through the normal report pipeline.

    These are deterministic compatibility facts, so they are evidence tier C
    (reachable, enumerated) - never blocking, but never an unproven hunch
    either. Severity reflects the worst cell: an outright incompatibility is
    high, a behavioural warning is medium.
    """
    rows = build_matrix(source, chains, solc_version=solc_version, evm_version=evm_version)
    findings: list[dict] = []
    for row in rows:
        incompatible = [k for k, v in row.cells.items() if v == "incompatible"]
        warns = [k for k, v in row.cells.items() if v == "warn"]
        if not incompatible and not warns:
            continue

        worst = "incompatible" if incompatible else "warn"
        affected = incompatible or warns
        names = ", ".join(CHAIN_FACTS[k].name for k in affected)
        reason = row.reasons.get(affected[0], "")
        severity = "high" if incompatible else "medium"
        verb = "breaks on" if incompatible else "behaves differently on"

        findings.append({
            "source": "paracheck-chain",
            "check": f"chain-{row.check_id}",
            "severity": severity,
            "confidence": "high",
            "title": f"{row.title} {verb} {names}",
            "description": (
                f"{row.title} appears in {file} and {verb} {names}. {reason}."
                if reason else f"{row.title} appears in {file} and {verb} {names}."
            ),
            "contract": None,
            "file": file,
            "lines": row.lines,
            "suggested_fix": row.fix or None,
            "evidence": "C",  # a deterministic compatibility fact, never a hunch, never blocking
            "evidence_detail": None,
        })
    return findings
