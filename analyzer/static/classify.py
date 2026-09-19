"""Classifies each contract state variable's storage-slot conflict risk from the
per-function read/write + index-origin info that run_slither.py extracts.

Rules (from the ParaCheck spec):
- A fixed global slot (plain value type, not a mapping/array) touched by more than one
  state-changing external function -> hot.
- A mapping/array index access that resolves to msg.sender or a function parameter
  -> that access is safe (each key is an independently computed slot).
- A mapping/array index access using a fixed/shared key (loop counters and literal
  indices count as fixed - they are not caller-specific) -> hot for that access.

Only state-changing (non-view/non-pure) external/public functions are considered - a
view/pure call is typically an off-chain eth_call, not a transaction, so it never enters
Monad's optimistic-parallel conflict/re-execution machinery. Constant and immutable
state variables are excluded entirely - they're baked into bytecode, not real storage
slots, so they can't conflict.

A "hot" flag only lists the functions whose *own* access pattern to that slot is unsafe.
A function that only ever indexes a shared mapping/array by a caller-scoped key does not
appear in that slot's flag, even if another function's access to the same slot is unsafe
(e.g. ShardedAMM's swap() vs. addLiquidity() on the same band-reserve mappings).
"""
from __future__ import annotations

from slither.core.declarations import Contract

from run_slither import FunctionAccess, _is_mapping_or_array


def _state_changing_accesses(function_accesses: list[FunctionAccess], contract: Contract) -> list[FunctionAccess]:
    changing_names = {
        f.name
        for f in contract.functions
        if f.visibility in ("external", "public") and not f.is_constructor and not f.view and not f.pure
    }
    return [fa for fa in function_accesses if fa.name in changing_names]


def classify(contract: Contract, function_accesses: list[FunctionAccess]) -> tuple[list[dict], int, list[str]]:
    accesses = _state_changing_accesses(function_accesses, contract)

    real_slots = {
        v.name: v
        for v in contract.state_variables
        if not v.is_constant and not v.is_immutable
    }

    touch_count: dict[str, set[str]] = {}
    for fa in accesses:
        for name in set(fa.reads) | set(fa.writes):
            if name not in real_slots:
                continue
            touch_count.setdefault(name, set()).add(fa.name)

    flags: list[dict] = []
    seen_hot_functions: set[str] = set()

    for name, functions in sorted(touch_count.items()):
        if _is_mapping_or_array(real_slots[name]):
            unsafe_functions = sorted(
                fa.name
                for fa in accesses
                if name in fa.caller_scoped_index and not fa.caller_scoped_index[name]
            )
            if unsafe_functions:
                flags.append({
                    "slot": name,
                    "touchedBy": unsafe_functions,
                    "severity": "hot",
                    "suggestedFix": (
                        f"'{name}' is indexed by a shared/fixed key in "
                        f"{', '.join(unsafe_functions)} - shard it by caller or another "
                        f"per-transaction key so concurrent calls resolve to different slots."
                    ),
                })
                seen_hot_functions.update(unsafe_functions)
        elif len(functions) > 1:
            touched_by = sorted(functions)
            flags.append({
                "slot": name,
                "touchedBy": touched_by,
                "severity": "hot",
                "suggestedFix": (
                    f"'{name}' is a single global slot written/read by "
                    f"{', '.join(touched_by)} - shard it (e.g. by price band, by caller) "
                    f"so concurrent calls touch different slots."
                ),
            })
            seen_hot_functions.update(touched_by)

    total_functions = {fa.name for fa in accesses}
    safe_functions = sorted(total_functions - seen_hot_functions)
    parallelism_score = round(100 * len(safe_functions) / len(total_functions)) if total_functions else 100

    return flags, parallelism_score, safe_functions
