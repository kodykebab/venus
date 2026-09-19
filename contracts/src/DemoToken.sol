// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "./interfaces/IERC20.sol";

/// @notice Minimal mintable ERC20 used to pair NaiveAMM/ShardedAMM for the ParaCheck demo.
/// mint() is unrestricted so anyone running the demo/load tooling can self-serve test
/// liquidity - this is testnet-only demo infrastructure, not production code.
contract DemoToken is IERC20 {
    string public name;
    string public symbol;
    uint8 public constant decimals = 18;

    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    constructor(string memory name_, string memory symbol_, uint256 initialSupply) {
        name = name_;
        symbol = symbol_;
        _mint(msg.sender, initialSupply);
    }

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _transfer(msg.sender, to, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        require(allowed >= amount, "INSUFFICIENT_ALLOWANCE");
        if (allowed != type(uint256).max) {
            allowance[from][msg.sender] = allowed - amount;
        }
        _transfer(from, to, amount);
        return true;
    }

    function _mint(address to, uint256 amount) internal {
        balanceOf[to] += amount;
        totalSupply += amount;
    }

    function _transfer(address from, address to, uint256 amount) internal {
        require(balanceOf[from] >= amount, "INSUFFICIENT_BALANCE");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
    }
}
