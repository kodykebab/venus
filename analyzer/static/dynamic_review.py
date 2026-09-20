"""Cross-references the static prediction against a measured simulation.

Static analysis says a slot *looks* contended. The simulation in
analyzer/dynamic/simulate.py runs the contract and measures whether concurrent
transactions actually collide on it. A finding that is both predicted and
measured is a different class of evidence from one that is only predicted, and
is reported as such.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dynamic"))

from schema import Finding  # noqa: E402


def storage_layout(contract) -> dict[int, str]:
    """slot number -> state variable name, for the contract's own storage.

    Mapping and array entries live at keccak-derived slots and deliberately
    aren't in here: those are per-key and are exactly what *isn't* contended."""
    layout: dict[int, str] = {}
    for variable in contract.state_variables_ordered:
        try:
            slot, _offset = contract.compilation_unit.storage_layout_of(contract, variable)
        except Exception:  # noqa: BLE001 - constants/immutables have no slot
            continue
        layout.setdefault(int(slot), variable.name)
    return layout


def name_contended_slots(contract, contended: dict[str, list[int]]) -> list[tuple[str, str, int]]:
    """Turns raw trace slot keys into (slot_key, variable_name, writer_count)."""
    layout = storage_layout(contract)
    named = []
    for slot_key, writers in contended.items():
        try:
            index = int(slot_key, 16)
        except ValueError:
            continue
        named.append((slot_key, layout.get(index, f"slot {slot_key}"), len(writers)))
    return sorted(named, key=lambda entry: -entry[2])


def simulation_findings(contract, result: dict, source_file: str | None) -> list[Finding]:
    """Findings from a measured run. These carry `high` confidence because they
    are observations, not inferences."""
    if not result.get("ran") or not result.get("contendedSlots"):
        return []

    senders = result.get("senders", 0)
    call = result.get("call", "the contract")
    pairs = result.get("conflictingTransactionPairs", 0)
    findings = []

    for slot_key, name, writers in name_contended_slots(contract, result["contendedSlots"]):
        lines = []
        for variable in contract.state_variables:
            if variable.name == name and variable.source_mapping:
                lines = list(variable.source_mapping.lines or [])
                break

        findings.append(
            Finding(
                source="paracheck-dynamic",
                check="hot-slot-confirmed",
                # Measured, not predicted - a step above the static guess.
                severity="high",
                confidence="high",
                title=(
                    f"`{name}` contention confirmed by simulation "
                    f"({writers} of {senders} concurrent calls collided)"
                ),
                description=(
                    f"{senders} concurrent `{call}` transactions were executed against a "
                    f"deployed instance of {contract.name} in a single block. {writers} of "
                    f"them wrote the same storage slot ({slot_key}), producing {pairs} "
                    f"colliding transaction pair(s). On a chain with optimistic parallel "
                    f"execution every one of those collisions is re-executed serially - this "
                    f"is measured from the execution trace, not inferred from the source."
                ),
                contract=contract.name,
                file=source_file,
                lines=lines,
                suggested_fix=(
                    f"Shard `{name}` so concurrent callers resolve to different slots "
                    f"(per-caller, per-band, or per-bucket), or move it off the hot path."
                ),
            )
        )
    return findings


def run_simulation(source_file: str, spec_data: dict, solc: str | None = None) -> dict:
    """Thin wrapper so callers don't need the dynamic package on their path."""
    from simulate import SimulationSpec, simulate

    return simulate(source_file, SimulationSpec.from_dict(spec_data), solc=solc)
