"""Runs Slither's full built-in detector suite and normalizes it into `Finding`s.

ParaCheck's own parallelism classifier covers one narrow category that no other
tool checks. Everything else a reviewer cares about - reentrancy, access control,
unchecked calls, gas waste - is already well covered by Slither's ~100 detectors,
so we run those rather than reimplementing them, and normalize both into one
schema (`schema.Finding`).
"""
from __future__ import annotations

import inspect
import re

from slither import Slither
from slither.detectors import all_detectors

from schema import Finding, severity_from_slither_impact

# Detectors that fire constantly on normal code and drown out real findings.
# Everything else in the suite runs.
NOISY_CHECKS = {
    "naming-convention",
    "solc-version",
    "pragma",
    "low-level-calls",
    "assembly",  # ParaCheck flags inline assembly itself, with its own reasoning
}

_TRAILING_LOCATION = re.compile(r"\s*\([^()]*\.sol#[\d\-L]+\)")


def available_detectors() -> list[type]:
    found = []
    for name in dir(all_detectors):
        if name.startswith("_"):
            continue
        obj = getattr(all_detectors, name)
        if inspect.isclass(obj) and hasattr(obj, "ARGUMENT"):
            found.append(obj)
    return found


def _title_from_description(description: str, check: str) -> str:
    """Slither descriptions are multi-line with inline source locations. The first
    line, minus those locations, reads as a decent one-line title."""
    first = description.strip().splitlines()[0] if description.strip() else check
    first = _TRAILING_LOCATION.sub("", first).strip().rstrip(":")
    if len(first) > 160:
        first = first[:157].rstrip() + "..."
    return first or check


def _location(result: dict) -> tuple[str | None, list[int], str | None]:
    """Pull file, lines, and owning contract off the first element of a result."""
    elements = result.get("elements") or []
    if not elements:
        return None, [], None

    mapping = elements[0].get("source_mapping") or {}
    file = mapping.get("filename_relative") or mapping.get("filename_short")
    lines = mapping.get("lines") or []

    contract = None
    element = elements[0]
    if element.get("type") == "contract":
        contract = element.get("name")
    else:
        parent = (element.get("type_specific_fields") or {}).get("parent") or {}
        while parent:
            if parent.get("type") == "contract":
                contract = parent.get("name")
                break
            parent = (parent.get("type_specific_fields") or {}).get("parent") or {}

    return file, lines, contract


def run_detectors(slither: Slither, skip_noisy: bool = True) -> list[Finding]:
    """Registers and runs the built-in suite against an already-loaded Slither
    instance, returning normalized findings. Never raises on an individual
    detector's failure - a single broken detector shouldn't lose every other
    finding in the run."""
    for detector in available_detectors():
        if skip_noisy and detector.ARGUMENT in NOISY_CHECKS:
            continue
        try:
            slither.register_detector(detector)
        except Exception:  # noqa: BLE001 - a detector that won't register is skipped, not fatal
            continue

    try:
        groups = slither.run_detectors()
    except Exception:  # noqa: BLE001 - never let the suite take down the whole analysis
        return []

    findings: list[Finding] = []
    for group in groups:
        for result in group or []:
            description = (result.get("description") or "").strip()
            file, lines, contract = _location(result)
            findings.append(
                Finding(
                    source="slither",
                    check=result.get("check", "unknown"),
                    severity=severity_from_slither_impact(result.get("impact", "Informational")),
                    confidence=(result.get("confidence") or "medium").lower(),
                    title=_title_from_description(description, result.get("check", "unknown")),
                    description=description,
                    contract=contract,
                    file=file,
                    lines=lines,
                )
            )
    return findings
