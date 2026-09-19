"""Wraps Slither's Python API to extract per-function storage read/write sets and
per-access index-origin information for one contract.

This is a deployment-local copy of analyzer/static/run_slither.py, adapted for the
upload-and-analyze endpoint: Vercel's Root Directory is set to demo-page/, so the
Python function can't reach files outside that tree, and it uses a bundled solc
binary + a single uploaded source file instead of a Foundry project + solc-select.
Keep in sync with analyzer/static/run_slither.py by hand - there's no build step
that does it automatically.

Never lets a Slither/crytic-compile failure crash the caller: every failure mode
(compile failure, SSA-conversion failure, inline assembly present) raises
UnanalyzableContract.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from slither import Slither
from slither.core.declarations import Contract, Function, SolidityVariableComposed
from slither.core.solidity_types import ArrayType, MappingType
from slither.core.variables.state_variable import StateVariable
from slither.slithir.operations import Index

# Matches an inline-assembly block start. Foundry/solc always normalize to this form
# regardless of source formatting (with or without a dialect string).
_INLINE_ASM_RE = re.compile(r"\bassembly\s*(\"[^\"]*\"\s*)?\{")

UNANALYZABLE_MESSAGE = (
    "This contract contains constructs that couldn't be statically analyzed - "
    "manual review recommended"
)


class UnanalyzableContract(Exception):
    """Raised for any condition where static analysis cannot be trusted."""

    def __init__(self, reason: str = UNANALYZABLE_MESSAGE):
        self.reason = reason
        super().__init__(reason)


@dataclass
class FunctionAccess:
    name: str
    visibility: str
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    caller_scoped_index: dict[str, bool] = field(default_factory=dict)


def has_inline_assembly(source_text: str) -> bool:
    return bool(_INLINE_ASM_RE.search(source_text))


def load_all_contracts(source_file: str, solc_path: str) -> list[Contract]:
    """Loads every top-level `contract` (not interface/library) in `source_file` via
    Slither, using an explicit bundled solc binary rather than PATH/solc-select.
    Raises UnanalyzableContract on any compile/SSA failure."""
    try:
        slither = Slither(source_file, solc=solc_path)
    except Exception as exc:  # noqa: BLE001 - crytic-compile/Slither raise many exception types
        raise UnanalyzableContract(f"{UNANALYZABLE_MESSAGE} (compile error: {exc})") from exc

    return [c for c in slither.contracts if c.contract_kind == "contract"]


def _is_mapping_or_array(variable: StateVariable) -> bool:
    return isinstance(variable.type, (MappingType, ArrayType))


def _is_caller_scoped(function: Function, variable, visited: set | None = None) -> bool:
    """True if `variable` is msg.sender, one of `function`'s own parameters, or is
    assigned (directly, or via a one-hop internal call argument) from one of those.
    Bounded, cycle-safe traversal of this function's own IR only."""
    if visited is None:
        visited = set()
    if id(variable) in visited:
        return False
    visited.add(id(variable))

    if isinstance(variable, SolidityVariableComposed) and variable.name == "msg.sender":
        return True
    if variable in function.parameters:
        return True

    for node in function.nodes:
        for ir in node.irs:
            if getattr(ir, "lvalue", None) is not variable:
                continue
            operands = []
            for attr in ("rvalue", "variable_right", "variable_left"):
                v = getattr(ir, attr, None)
                if v is not None:
                    operands.append(v)
            operands.extend(getattr(ir, "arguments", None) or [])
            for operand in operands:
                if operand is variable:
                    continue
                if _is_caller_scoped(function, operand, visited):
                    return True
    return False


def extract_function_access(contract: Contract) -> list[FunctionAccess]:
    """Per externally-reachable function: which state variables it reads/writes, and for
    mapping/array variables, whether every index access in that function is caller-scoped."""
    results: list[FunctionAccess] = []

    for function in contract.functions:
        if function.visibility not in ("external", "public") or function.is_constructor:
            continue

        access = FunctionAccess(
            name=function.name,
            visibility=function.visibility,
            reads=[v.name for v in function.state_variables_read],
            writes=[v.name for v in function.state_variables_written],
        )

        touched = {v.name: v for v in (function.state_variables_read + function.state_variables_written)}
        for name, variable in touched.items():
            if not _is_mapping_or_array(variable):
                continue
            index_vars = [
                ir.variable_right
                for node in function.nodes
                for ir in node.irs
                if isinstance(ir, Index) and ir.variable_left == variable
            ]
            access.caller_scoped_index[name] = bool(index_vars) and all(
                _is_caller_scoped(function, idx) for idx in index_vars
            )

        results.append(access)

    return results
