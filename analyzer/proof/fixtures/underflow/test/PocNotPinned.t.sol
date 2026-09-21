// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// A PoC that does not depend on the bug at all: it passes whether the Vault is
// vulnerable or patched, so the validator must reject it as not pinned.
contract PocNotPinned {
    function testTrivial() external pure {
        require(1 + 1 == 2, "math");
    }
}
