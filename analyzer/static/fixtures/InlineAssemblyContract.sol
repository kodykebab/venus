// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Fixture: raw sstore/sload in inline assembly. The analyzer must bail out
/// gracefully with `unanalyzable: true` rather than mis-classify or crash.
contract InlineAssemblyContract {
    uint256 private value;

    function setValue(uint256 newValue) external {
        assembly {
            sstore(value.slot, newValue)
        }
    }

    function getValue() external view returns (uint256 result) {
        assembly {
            result := sload(value.slot)
        }
    }
}
