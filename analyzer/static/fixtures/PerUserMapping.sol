// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Fixture: a mapping indexed by msg.sender. Each caller's storage slot is
/// independently computed, so the static classifier must flag `balances` as safe.
contract PerUserMapping {
    mapping(address => uint256) public balances;

    function deposit() external payable {
        balances[msg.sender] += msg.value;
    }

    function withdraw(uint256 amount) external {
        require(balances[msg.sender] >= amount, "INSUFFICIENT");
        balances[msg.sender] -= amount;
        payable(msg.sender).transfer(amount);
    }
}
