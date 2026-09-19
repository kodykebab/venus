#!/usr/bin/env python3
"""CLI entry point: analyze one contract and emit the ParaCheck static-report JSON shape.

    python report.py <project_path> <ContractName> <source_file> [--out FILE] [--foundry-out out]

On any failure - Slither/crytic-compile error, SSA-conversion failure, or inline assembly
detected in the source - emits `{"unanalyzable": true, "reason": "..."}` instead of
crashing or silently producing an empty/misleading report.
"""
from __future__ import annotations

import argparse
import json
import sys

from classify import classify
from run_slither import UnanalyzableContract, extract_function_access, load_contract


def analyze_contract(project_path: str, contract_name: str, source_file: str, foundry_out_directory: str = "out") -> dict:
    try:
        contract = load_contract(project_path, contract_name, source_file, foundry_out_directory)
        function_accesses = extract_function_access(contract)
        flags, parallelism_score, safe_functions = classify(contract, function_accesses)
    except UnanalyzableContract as exc:
        return {
            "contract": contract_name,
            "parallelismScore": None,
            "flags": [],
            "unanalyzable": True,
            "reason": exc.reason,
        }
    except Exception as exc:  # noqa: BLE001 - never let an unexpected Slither error crash silently
        return {
            "contract": contract_name,
            "parallelismScore": None,
            "flags": [],
            "unanalyzable": True,
            "reason": f"Unexpected static-analysis failure - manual review recommended ({exc})",
        }

    return {
        "contract": contract_name,
        "parallelismScore": parallelism_score,
        "flags": flags,
        "safeFunctions": safe_functions,
        "unanalyzable": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_path")
    parser.add_argument("contract_name")
    parser.add_argument("source_file")
    parser.add_argument("--foundry-out", default="out")
    parser.add_argument("--out", default=None, help="write JSON to this file instead of stdout")
    args = parser.parse_args()

    report = analyze_contract(args.project_path, args.contract_name, args.source_file, args.foundry_out)
    output = json.dumps(report, indent=2)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(output + "\n")
    else:
        print(output)

    if report["unanalyzable"]:
        sys.exit(0)  # graceful, not a crash - exit 0 so CI/demo pipelines don't treat this as failure


if __name__ == "__main__":
    main()
