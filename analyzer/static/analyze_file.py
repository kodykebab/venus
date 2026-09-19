#!/usr/bin/env python3
"""CLI entry point: analyze every contract in a single, importless Solidity file.

    python analyze_file.py <path/to/Contract.sol> [--solc PATH] [--out FILE]

Backs the root-level `paracheck <file>.sol` command. Uses whatever `solc` is on PATH
(solc-select's active version) by default - pass --solc for an explicit binary, e.g.
the one bundled for Vercel at demo-page/api/_analyzer/solc-linux-amd64.

On any failure - Slither/crytic-compile error, SSA-conversion failure, inline assembly,
or an `import` statement (this mode doesn't resolve imports) - emits
`{"unanalyzable": true, "reason": "..."}` instead of crashing or silently skipping.
"""
from __future__ import annotations

import argparse
import json
import sys

from classify import classify
from run_slither import UnanalyzableContract, extract_function_access, load_all_contracts


def analyze_file(source_file: str, solc: str | None = None) -> dict:
    try:
        contracts = load_all_contracts(source_file, solc=solc)
    except UnanalyzableContract as exc:
        return {"unanalyzable": True, "reason": exc.reason, "contracts": []}
    except Exception as exc:  # noqa: BLE001 - never let an unexpected Slither error crash silently
        return {
            "unanalyzable": True,
            "reason": f"Unexpected static-analysis failure - manual review recommended ({exc})",
            "contracts": [],
        }

    if not contracts:
        return {
            "unanalyzable": True,
            "reason": "No contracts found (only interfaces/libraries, or the file didn't parse).",
            "contracts": [],
        }

    reports = []
    for contract in contracts:
        function_accesses = extract_function_access(contract)
        flags, parallelism_score, safe_functions = classify(contract, function_accesses)
        reports.append({
            "contract": contract.name,
            "parallelismScore": parallelism_score,
            "flags": flags,
            "safeFunctions": safe_functions,
            "unanalyzable": False,
        })

    return {"unanalyzable": False, "contracts": reports}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_file")
    parser.add_argument("--solc", default=None, help="explicit solc binary path (default: solc-select's active version on PATH)")
    parser.add_argument("--out", default=None, help="write JSON to this file instead of stdout")
    args = parser.parse_args()

    report = analyze_file(args.source_file, solc=args.solc)
    output = json.dumps(report, indent=2)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(output + "\n")
    else:
        print(output)

    if report["unanalyzable"]:
        sys.exit(0)  # graceful, not a crash


if __name__ == "__main__":
    main()
