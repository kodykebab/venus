// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Fixture: a single global counter touched by two external functions.
/// The static classifier must flag `count` as hot.
contract GlobalCounter {
    uint256 public count;

    function increment() external {
        count += 1;
    }

    function incrementBy(uint256 amount) external {
        count += amount;
    }
}
