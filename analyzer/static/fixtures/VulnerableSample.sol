// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract Vulnerable {
    mapping(address => uint256) public balances;
    uint256 public total;
    address public owner;

    function setOwner(address newOwner) external {
        owner = newOwner;
    }

    function deposit() external payable {
        balances[msg.sender] += msg.value;
        total += msg.value;
    }

    function withdraw(uint256 amount) external {
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "fail");
        balances[msg.sender] -= amount;
        total -= amount;
    }

    function drain(address payable to) external {
        to.transfer(address(this).balance);
    }
}
