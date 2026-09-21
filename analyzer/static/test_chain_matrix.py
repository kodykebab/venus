"""Chain Matrix: deterministic cross-chain compatibility checks over source."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from chain_matrix import (
    build_matrix,
    matrix_findings,
    matrix_to_dict,
)

TRANSFER_SRC = """// SPDX-License-Identifier: MIT
pragma solidity 0.8.19;

contract Payouts {
    function pay(address payable to, uint256 amount) external {
        to.transfer(amount);
    }
}
"""

TIMING_SRC = """pragma solidity ^0.8.24;
contract Lock {
    uint256 start;
    function locked() external view returns (bool) {
        return block.number < start + 100;
    }
}
"""


def _row(rows, check_id):
    return next((r for r in rows if r.check_id == check_id), None)


def test_fixed_gas_transfer_is_incompatible_on_zksync_only():
    rows = build_matrix(TRANSFER_SRC, ["ethereum", "zksync-era", "base"])
    row = _row(rows, "fixed-gas-transfer")
    assert row is not None and row.lines == [6]
    assert row.cells["ethereum"] == "ok"
    assert row.cells["base"] == "ok"
    assert row.cells["zksync-era"] == "incompatible"


def test_push0_flags_modern_compiler_on_non_push0_chains():
    # 0.8.19 predates PUSH0 emission, so no row at all.
    assert _row(build_matrix(TRANSFER_SRC), "push0") is None

    # 0.8.24 emits PUSH0 by default; a chain without it is incompatible.
    rows = build_matrix(TIMING_SRC, ["ethereum", "zksync-era"])
    push0 = _row(rows, "push0")
    assert push0 is not None
    assert push0.cells["ethereum"] == "ok"
    assert push0.cells["zksync-era"] == "incompatible"


def test_push0_suppressed_when_evm_version_pinned_below_shanghai():
    rows = build_matrix(TIMING_SRC, ["zksync-era"], evm_version="paris")
    assert _row(rows, "push0") is None


def test_block_number_timing_warns_on_arbitrum_only():
    rows = build_matrix(TIMING_SRC, ["ethereum", "arbitrum", "optimism"])
    row = _row(rows, "block-number-timing")
    assert row is not None
    assert row.cells["ethereum"] == "ok"
    assert row.cells["optimism"] == "ok"
    assert row.cells["arbitrum"] == "warn"


def test_absent_constructs_produce_no_rows():
    clean = "pragma solidity 0.8.19;\ncontract C { uint256 x; }"
    assert build_matrix(clean) == []


def test_comment_mentions_do_not_fire():
    commented = "pragma solidity 0.8.19;\ncontract C {\n  // uses selfdestruct(payable(x)) elsewhere\n}"
    assert _row(build_matrix(commented), "selfdestruct") is None


def test_findings_are_tier_c_and_never_block():
    findings = matrix_findings(TRANSFER_SRC, "src/Payouts.sol", chains=["ethereum", "zksync-era"])
    assert findings, "an incompatibility must surface as a finding"
    f = findings[0]
    assert f["evidence"] == "C"  # deterministic, informing, never blocking
    assert f["check"] == "chain-fixed-gas-transfer"
    assert f["severity"] == "high"  # an outright incompatibility
    assert "zkSync Era" in f["title"]
    assert f["suggested_fix"]


def test_findings_omit_constructs_that_are_ok_everywhere():
    # transfer() checked only against chains where it is fine -> no finding.
    findings = matrix_findings(TRANSFER_SRC, "src/Payouts.sol", chains=["ethereum", "base"])
    assert findings == []


def test_matrix_serializes_for_the_api():
    rows = build_matrix(TRANSFER_SRC, ["ethereum", "zksync-era"])
    payload = matrix_to_dict(rows, ["ethereum", "zksync-era"])
    assert payload["chains"] == [
        {"key": "ethereum", "name": "Ethereum"},
        {"key": "zksync-era", "name": "zkSync Era"},
    ]
    assert payload["rows"][0]["cells"]["zksync-era"] == "incompatible"
