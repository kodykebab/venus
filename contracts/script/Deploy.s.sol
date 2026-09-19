// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {DemoToken} from "../src/DemoToken.sol";
import {NaiveAMM} from "../src/NaiveAMM.sol";
import {ShardedAMM} from "../src/ShardedAMM.sol";

/// @notice Deploys the two demo tokens, NaiveAMM, and ShardedAMM (default 3 bands), and
/// seeds both AMMs with equal starting liquidity so they're immediately swappable.
contract Deploy is Script {
    uint256 constant INITIAL_SUPPLY = 10_000_000e18;
    uint256 constant SEED_LIQUIDITY = 1_000_000e18;
    uint256 constant BAND_COUNT = 3;
    uint256 constant BAND_WIDTH = 1_000e18;

    function run() external {
        vm.startBroadcast();

        DemoToken token0 = new DemoToken("ParaCheck Token A", "PCA", INITIAL_SUPPLY);
        DemoToken token1 = new DemoToken("ParaCheck Token B", "PCB", INITIAL_SUPPLY);

        NaiveAMM naive = new NaiveAMM(address(token0), address(token1));
        ShardedAMM sharded = new ShardedAMM(address(token0), address(token1), BAND_COUNT, BAND_WIDTH);

        token0.approve(address(naive), SEED_LIQUIDITY);
        token1.approve(address(naive), SEED_LIQUIDITY);
        naive.addLiquidity(SEED_LIQUIDITY, SEED_LIQUIDITY);

        token0.approve(address(sharded), SEED_LIQUIDITY);
        token1.approve(address(sharded), SEED_LIQUIDITY);
        sharded.addLiquidity(SEED_LIQUIDITY, SEED_LIQUIDITY);

        vm.stopBroadcast();

        console.log("token0:", address(token0));
        console.log("token1:", address(token1));
        console.log("NaiveAMM:", address(naive));
        console.log("ShardedAMM:", address(sharded));
    }
}
