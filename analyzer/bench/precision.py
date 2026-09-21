"""Precision benchmark: the number no competitor publishes.

Every vendor in this space quotes recall - how many known bugs their tool finds.
None publishes precision, because the standard benchmark cannot produce it (it
holds a curated subset, not the full set of what a tool shouts about). The gap
this measures is the one a developer actually feels: on already-audited,
already-fixed code, how many findings does the tool put in front of a human, and
how many of those are allowed to block a merge?

For ParaCheck the blocking number should be near zero on clean code, by
construction: only a proven finding (an exploit test that reproduces) blocks, and
audited code has few of those. A raw scanner emits dozens per file. This harness
runs the real pipeline over a set of Solidity trees and prints that contrast.

Usage:
    python bench/precision.py <path-to-solidity-tree> [<path> ...]

It reports, per tree and in total: files, kLOC, total findings, the split by
evidence tier, and the count that would block a merge (proven only). Run against
audited code, a low blocking count is the product's whole thesis, measured.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static"))

from review import review_file  # noqa: E402

SKIP_DIRS = {"lib", "node_modules", "out", "cache", "artifacts", "forge-std", ".git", "test", "tests"}


def _solidity_files(root: str) -> list[str]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name.endswith(".sol"):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def _loc(path: str) -> int:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return sum(1 for line in handle if line.strip() and not line.strip().startswith("//"))
    except OSError:
        return 0


def measure_tree(root: str, solc: str | None = None) -> dict:
    files = _solidity_files(root)
    total_loc = 0
    by_tier: dict[str, int] = {}
    total = 0
    blocking = 0

    for path in files:
        total_loc += _loc(path)
        try:
            report = review_file(path, solc=solc)
        except Exception as exc:  # a file that will not compile is not a crash
            print(f"  ! skipped {os.path.relpath(path, root)}: {type(exc).__name__}")
            continue
        for finding in report.get("findings", []):
            total += 1
            tier = finding.get("evidence", "D")
            by_tier[tier] = by_tier.get(tier, 0) + 1
            if tier in ("A", "B"):
                blocking += 1

    kloc = total_loc / 1000 or 1e-9
    return {
        "root": root,
        "files": len(files),
        "loc": total_loc,
        "total_findings": total,
        "by_tier": by_tier,
        "blocking": blocking,
        "findings_per_kloc": round(total / kloc, 1),
        "blocking_per_kloc": round(blocking / kloc, 2),
    }


def _print_row(name: str, m: dict) -> None:
    tiers = " ".join(f"{t}:{m['by_tier'].get(t, 0)}" for t in ("A", "B", "C", "D"))
    print(f"{name:<28} files={m['files']:<4} kLOC={m['loc']/1000:>6.1f} "
          f"findings={m['total_findings']:<4} [{tiers}] "
          f"blocking={m['blocking']:<3} noise/kLOC={m['findings_per_kloc']}")


def main(paths: list[str]) -> int:
    if not paths:
        print(__doc__)
        return 2

    results = []
    print("=" * 100)
    for path in paths:
        name = os.path.basename(os.path.normpath(path))
        print(f"Scanning {name} ...")
        m = measure_tree(path)
        results.append(m)
        _print_row(name, m)
    print("=" * 100)

    agg_loc = sum(r["loc"] for r in results)
    agg_total = sum(r["total_findings"] for r in results)
    agg_block = sum(r["blocking"] for r in results)
    kloc = agg_loc / 1000 or 1e-9
    print(f"{'TOTAL':<28} files={sum(r['files'] for r in results):<4} kLOC={agg_loc/1000:>6.1f} "
          f"findings={agg_total:<4} blocking={agg_block:<3} "
          f"noise/kLOC={round(agg_total/kloc, 1)} blocking/kLOC={round(agg_block/kloc, 2)}")
    print()
    print("Interpretation: 'noise/kLOC' is what a human would have to triage; the "
          "industry baseline for raw scanners is 40-90. 'blocking' is what would "
          "fail a merge - proven findings only. On audited code that number should "
          "be near zero, which is the point.")

    if os.environ.get("PARACHECK_BENCH_JSON"):
        print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
