"""Orchestrates every static analyzer over one source file into a single report.

Compiles once, then runs both passes over the same Slither instance:
  - ParaCheck's parallelism-conflict classifier (the category nothing else checks)
  - Slither's built-in detector suite (reentrancy, access control, gas, ...)

Both normalize into `schema.Finding`, so the CLI, the GitHub Action, the web UI,
and the LLM synthesis layer all consume one shape.
"""
from __future__ import annotations

import os

from slither import Slither

from classify import classify
from detectors import run_detectors
from project import detect_project, install_dependencies
from run_slither import (
    UNANALYZABLE_MESSAGE,
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


def _is_dependency(contract) -> bool:
    """forge-std, OpenZeppelin and friends compile alongside the project. Reviewing
    them would bury the author's own code under hundreds of third-party findings."""
    if contract.is_from_dependency():
        return True
    mapping = contract.source_mapping
    if not mapping or not mapping.filename:
        return True
    relative = (mapping.filename.relative or "").replace(os.sep, "/")
    return any(part in relative.split("/") for part in ("lib", "node_modules"))


def _normalize(path: str) -> str:
    return os.path.normpath(path).replace(os.sep, "/").lstrip("./")


def _repo_root(start: str) -> str:
    """Nearest enclosing git checkout, so reported paths match what GitHub uses for
    PR annotations regardless of which directory the tool was invoked from."""
    current = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.abspath(start)
        current = parent


def _anchor_path(path: str | None, base: str) -> str | None:
    """Rewrites a Slither-reported path (relative to its own cwd) into a path
    relative to `base`. Stable across invocation directories."""
    if not path:
        return path
    absolute = path if os.path.isabs(path) else os.path.abspath(path)
    try:
        return _normalize(os.path.relpath(absolute, base))
    except ValueError:  # different drive on Windows
        return _normalize(path)


def review_project(
    root: str,
    changed_files: list[str] | None = None,
    min_severity: str = "info",
    install: bool = True,
) -> dict:
    """Reviews a real multi-file project - resolves imports, unlike review_file.

    `changed_files` scopes the *output* to a pull request's files. Analysis still
    runs over the whole project, because whether a slot is contended is a property
    of the entire contract, not of the lines a diff happens to touch."""
    project = detect_project(root)

    if install and project.is_installable:
        ok, reason = install_dependencies(project)
        if not ok:
            return {
                "unanalyzable": True,
                "reason": f"Could not prepare the project for analysis - {reason}",
                "contracts": [],
                "findings": [],
                "project": {"framework": project.framework, "root": project.root},
            }

    try:
        slither = Slither(project.root)
    except Exception as exc:  # noqa: BLE001
        return {
            "unanalyzable": True,
            "reason": f"{UNANALYZABLE_MESSAGE} (compile error: {exc})",
            "contracts": [],
            "findings": [],
            "project": {"framework": project.framework, "root": project.root},
        }

    contracts = [c for c in contracts_of(slither) if not _is_dependency(c)]
    if not contracts:
        return {
            "unanalyzable": True,
            "reason": "No first-party contracts found in this project.",
            "contracts": [],
            "findings": [],
            "project": {"framework": project.framework, "root": project.root},
        }

    reports: list[dict] = []
    findings: list[Finding] = []
    for contract in contracts:
        accesses = extract_function_access(contract)
        flags, score, safe_functions = classify(contract, accesses)
        reports.append(
            {
                "contract": contract.name,
                "file": _source_file_of(contract),
                "parallelismScore": score,
                "flags": flags,
                "safeFunctions": safe_functions,
                "unanalyzable": False,
            }
        )
        findings.extend(_parallelism_findings(contract, flags))

    findings.extend(run_detectors(slither))

    # Slither reports paths relative to its own working directory; re-anchor
    # everything to the repository root so the same finding gets the same path
    # whether CI runs from the repo root or from a subdirectory.
    base = _repo_root(project.root)
    for finding in findings:
        finding.file = _anchor_path(finding.file, base)
    for report_entry in reports:
        report_entry["file"] = _anchor_path(report_entry.get("file"), base)

    # Drop dependency findings, then scope to the change under review.
    findings = [f for f in findings if f.file and not _looks_like_dependency(f.file)]
    if changed_files:
        wanted = {_normalize(p) for p in changed_files}
        findings = [f for f in findings if _normalize(f.file or "") in wanted]
        reports = [r for r in reports if _normalize(r.get("file") or "") in wanted]

    findings = sort_findings(filter_findings(findings, min_severity))
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1

    return {
        "unanalyzable": False,
        "project": {"framework": project.framework, "root": project.root},
        "contracts": reports,
        "findings": [f.to_dict() for f in findings],
        "summary": {
            "totalFindings": len(findings),
            "bySeverity": counts,
            "lowestParallelismScore": min((r["parallelismScore"] for r in reports), default=None),
            "contractsReviewed": len(reports),
        },
    }


def _looks_like_dependency(path: str) -> bool:
    parts = _normalize(path).split("/")
    return "lib" in parts or "node_modules" in parts
