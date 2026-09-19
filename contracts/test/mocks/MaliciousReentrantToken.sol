// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "../../src/interfaces/IERC20.sol";
import {IAMM} from "../../src/interfaces/IAMM.sol";

/// @notice ERC20 whose transfer() reenters a target AMM's swap() once. Used only to prove
/// the AMM's nonReentrant guard rejects a hostile/callback token acting as tokenOut.
contract MaliciousReentrantToken is IERC20 {
    string public constant name = "Malicious";
    string public constant symbol = "EVIL";
    uint8 public constant decimals = 18;

    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    IAMM public target;
    address public attackTokenIn;
    bool private _attacking;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
        totalSupply += amount;
    }

    function setAttack(IAMM target_, address attackTokenIn_) external {
        target = target_;
        attackTokenIn = attackTokenIn_;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _maybeReenter();
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

    function _maybeReenter() internal {
        if (address(target) != address(0) && !_attacking) {
            _attacking = true;
            target.swap(attackTokenIn, 1e18, 0);
            _attacking = false;
        }
    }

    function _transfer(address from, address to, uint256 amount) internal {
        require(balanceOf[from] >= amount, "INSUFFICIENT_BALANCE");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
    }
}
