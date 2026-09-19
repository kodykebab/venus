"""Vercel Python serverless function: upload-and-analyze endpoint.

POST { "source": "<solidity source>" } and get back the same report shape as the
committed demo-page/reports/static-*.json files, computed fresh against whatever was
uploaded - one entry per top-level `contract` found in the file.

Uses a bundled solc binary (fixed at 0.8.24, matching this repo's own contracts)
rather than solc-select, since a public serverless function downloading arbitrary
compiler versions per-request would be slow, and to build any pragma requested.
Contracts requiring a materially different Solidity version will fail to compile -
that's a known limitation, not a silent wrong answer (it comes back as
`unanalyzable: true`, never a crash or a mis-classification).
"""
import json
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_analyzer"))

from classify import classify  # noqa: E402
from run_slither import (  # noqa: E402
    UnanalyzableContract,
    extract_function_access,
    has_inline_assembly,
    load_all_contracts,
)

SOLC_PATH = os.path.join(os.path.dirname(__file__), "_analyzer", "solc-linux-amd64")
MAX_SOURCE_BYTES = 100_000


def analyze_source(source: str) -> dict:
    if not source or not source.strip():
        return {"unanalyzable": True, "reason": "No source provided.", "contracts": []}
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return {
            "unanalyzable": True,
            "reason": f"Source too large ({len(source.encode('utf-8'))} bytes) - limit is {MAX_SOURCE_BYTES} bytes.",
            "contracts": [],
        }
    if has_inline_assembly(source):
        return {
            "unanalyzable": True,
            "reason": "This contract contains constructs that couldn't be statically analyzed - manual review recommended",
            "contracts": [],
        }

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sol", delete=False) as tmp:
            tmp.write(source)
            tmp_path = tmp.name

        try:
            contracts = load_all_contracts(tmp_path, SOLC_PATH)
        except UnanalyzableContract as exc:
            return {"unanalyzable": True, "reason": exc.reason, "contracts": []}

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
    except Exception as exc:  # noqa: BLE001 - never crash the endpoint on unexpected errors
        return {
            "unanalyzable": True,
            "reason": f"Unexpected static-analysis failure - manual review recommended ({exc})",
            "contracts": [],
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            data = json.loads(body or b"{}")
            result = analyze_source(data.get("source", ""))
            status = 200
        except json.JSONDecodeError:
            result = {"unanalyzable": True, "reason": "Invalid JSON body.", "contracts": []}
            status = 400
        except Exception as exc:  # noqa: BLE001
            result = {"unanalyzable": True, "reason": f"Server error: {exc}", "contracts": []}
            status = 500

        body_out = json.dumps(result).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body_out)))
        self.end_headers()
        self.wfile.write(body_out)
