"""Orchestrates every static analyzer over one source file into a single report.

Compiles once, then runs both passes over the same Slither instance:
  - ParaCheck's parallelism-conflict classifier (the category nothing else checks)
  - Slither's built-in detector suite (reentrancy, access control, gas, ...)

Both normalize into `schema.Finding`, so the CLI, the GitHub Action, the web UI,
and the LLM synthesis layer all consume one shape.
"""
from __future__ import annotations

from classify import classify
from detectors import run_detectors
from run_slither import (
    UnanalyzableContract,
    contracts_of,
    extract_function_access,
    load_slither,
)
from schema import Finding, filter_findings, sort_findings

# A contended storage slot is a throughput/cost problem rather than a security
# hole, but on a parallel-execution chain it silently serializes the contract -
# high enough to surface above the informational noise, not a "critical".
HOT_SLOT_SEVERITY = "medium"


def _slot_lines(contract, slot_name: str) -> list[int]:
    for variable in contract.state_variables:
        if variable.name == slot_name and variable.source_mapping:
            return list(variable.source_mapping.lines or [])
    return []


def _source_file_of(contract) -> str | None:
    """Slither's Source objects expose the path under .filename.relative; detector
    results use a plain dict with a different key, hence the separate accessor."""
    mapping = contract.source_mapping
    if not mapping or not mapping.filename:
        return None
    return mapping.filename.relative or mapping.filename.short


def _parallelism_findings(contract, flags: list[dict]) -> list[Finding]:
    findings = []
    for flag in flags:
        touched = ", ".join(flag["touchedBy"])
        findings.append(
            Finding(
                source="paracheck",
                check="hot-slot",
                severity=HOT_SLOT_SEVERITY,
                confidence="high",
                title=f"`{flag['slot']}` is a contended storage slot (touched by {touched})",
                description=(
                    f"Every concurrent call to {touched} writes the same storage slot "
                    f"`{flag['slot']}`. Under optimistic parallel execution these "
                    f"transactions conflict and get re-executed serially, so the "
                    f"contract loses the throughput the chain is built to provide."
                ),
                contract=contract.name,
                file=_source_file_of(contract),
                lines=_slot_lines(contract, flag["slot"]),
                suggested_fix=flag.get("suggestedFix"),
            )
        )
    return findings


def review_file(source_file: str, solc: str | None = None, min_severity: str = "info") -> dict:
    """Full static review of one self-contained Solidity file. Never raises - every
    failure mode comes back as `unanalyzable: true` with a reason."""
    try:
        slither = load_slither(source_file, solc=solc)
    except UnanalyzableContract as exc:
        return {"unanalyzable": True, "reason": exc.reason, "contracts": [], "findings": []}
    except Exception as exc:  # noqa: BLE001
        return {
            "unanalyzable": True,
            "reason": f"Unexpected static-analysis failure - manual review recommended ({exc})",
            "contracts": [],
            "findings": [],
        }

    contracts = contracts_of(slither)
    if not contracts:
        return {
            "unanalyzable": True,
            "reason": "No contracts found (only interfaces/libraries, or the file didn't parse).",
            "contracts": [],
            "findings": [],
        }

    reports: list[dict] = []
    findings: list[Finding] = []

    for contract in contracts:
        accesses = extract_function_access(contract)
        flags, score, safe_functions = classify(contract, accesses)
        reports.append(
            {
                "contract": contract.name,
                "parallelismScore": score,
                "flags": flags,
                "safeFunctions": safe_functions,
                "unanalyzable": False,
            }
        )
        findings.extend(_parallelism_findings(contract, flags))

    # Detectors run once for the whole compilation unit, not per contract.
    findings.extend(run_detectors(slither))

    # Slither reports paths relative to its own compilation root, which for a
    # temp/absolute target comes out as ../../../.. noise. Every finding here
    # belongs to the one file the caller named, so report it under that path -
    # it's also what inline PR annotations need.
    for finding in findings:
        finding.file = source_file

    findings = sort_findings(filter_findings(findings, min_severity))
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1

    return {
        "unanalyzable": False,
        "contracts": reports,
        "findings": [f.to_dict() for f in findings],
        "summary": {
            "totalFindings": len(findings),
            "bySeverity": counts,
            "lowestParallelismScore": min((r["parallelismScore"] for r in reports), default=None),
        },
    }
