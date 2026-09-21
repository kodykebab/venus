// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// Deliberately vulnerable fixture: withdraw subtracts in an unchecked block
// with no balance check, so a caller who never deposited underflows to a huge
// balance instead of reverting.
contract Vault {
    mapping(address => uint256) public balance;

    function deposit() external payable {
        balance[msg.sender] += msg.value;
    }

    function withdraw(uint256 amount) external {
        unchecked {
            balance[msg.sender] -= amount;
        }
    }
}
