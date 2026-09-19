// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {NaiveAMM} from "../src/NaiveAMM.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {MaliciousReentrantToken} from "./mocks/MaliciousReentrantToken.sol";

contract NaiveAMMTest is Test {
    NaiveAMM amm;
    MockERC20 token0;
    MockERC20 token1;

    address lp = makeAddr("lp");
    address trader = makeAddr("trader");

    uint256 constant INITIAL_LIQUIDITY = 1_000_000e18;

    function setUp() public {
        token0 = new MockERC20("Token0", "TK0");
        token1 = new MockERC20("Token1", "TK1");
        amm = new NaiveAMM(address(token0), address(token1));

        token0.mint(lp, INITIAL_LIQUIDITY);
        token1.mint(lp, INITIAL_LIQUIDITY);

        vm.startPrank(lp);
        token0.approve(address(amm), type(uint256).max);
        token1.approve(address(amm), type(uint256).max);
        amm.addLiquidity(INITIAL_LIQUIDITY, INITIAL_LIQUIDITY);
        vm.stopPrank();
    }

    function test_AddLiquidity_UpdatesReserves() public view {
        (uint256 r0, uint256 r1) = amm.getReserves();
        assertEq(r0, INITIAL_LIQUIDITY);
        assertEq(r1, INITIAL_LIQUIDITY);
    }

    function test_RevertWhen_AddLiquidityZeroAmount() public {
        vm.prank(lp);
        vm.expectRevert(bytes("ZERO_AMOUNT"));
        amm.addLiquidity(0, 1e18);
    }

    function test_Swap_Normal() public {
        uint256 amountIn = 1_000e18;
        token0.mint(trader, amountIn);

        vm.startPrank(trader);
        token0.approve(address(amm), amountIn);
        uint256 amountOut = amm.swap(address(token0), amountIn, 0);
        vm.stopPrank();

        assertGt(amountOut, 0);
        assertEq(token1.balanceOf(trader), amountOut);

        (uint256 r0, uint256 r1) = amm.getReserves();
        assertEq(r0, INITIAL_LIQUIDITY + amountIn);
        assertEq(r1, INITIAL_LIQUIDITY - amountOut);
    }

    function test_Swap_BoundaryAmount_LargeSwapSucceeds() public {
        // Swap nearly the entire counter-reserve's worth of input; must not overflow
        // or revert, and output must stay strictly less than reserveOut.
        uint256 amountIn = INITIAL_LIQUIDITY * 100;
        token0.mint(trader, amountIn);

        vm.startPrank(trader);
        token0.approve(address(amm), amountIn);
        uint256 amountOut = amm.swap(address(token0), amountIn, 0);
        vm.stopPrank();

        assertLt(amountOut, INITIAL_LIQUIDITY);
    }

    function test_RevertWhen_SwapZeroAmount() public {
        vm.prank(trader);
        vm.expectRevert(bytes("ZERO_AMOUNT"));
        amm.swap(address(token0), 0, 0);
    }

    function test_RevertWhen_SwapInvalidToken() public {
        MockERC20 other = new MockERC20("Other", "OTH");
        vm.prank(trader);
        vm.expectRevert(bytes("INVALID_TOKEN"));
        amm.swap(address(other), 1e18, 0);
    }

    function test_RevertWhen_SwapSlippageExceeded() public {
        uint256 amountIn = 1_000e18;
        token0.mint(trader, amountIn);

        vm.startPrank(trader);
        token0.approve(address(amm), amountIn);
        vm.expectRevert(bytes("SLIPPAGE"));
        amm.swap(address(token0), amountIn, type(uint256).max);
        vm.stopPrank();
    }

    function test_RevertWhen_ReentrantSwap() public {
        // Redeploy with token1 replaced by a hostile token whose transfer() reenters swap().
        MaliciousReentrantToken evilToken1 = new MaliciousReentrantToken();
        NaiveAMM evilAmm = new NaiveAMM(address(token0), address(evilToken1));

        token0.mint(lp, INITIAL_LIQUIDITY);
        evilToken1.mint(lp, INITIAL_LIQUIDITY);
        vm.startPrank(lp);
        token0.approve(address(evilAmm), type(uint256).max);
        evilToken1.approve(address(evilAmm), type(uint256).max);
        evilAmm.addLiquidity(INITIAL_LIQUIDITY, INITIAL_LIQUIDITY);
        vm.stopPrank();

        evilToken1.setAttack(evilAmm, address(token0));

        uint256 amountIn = 1_000e18;
        token0.mint(trader, amountIn);
        vm.startPrank(trader);
        token0.approve(address(evilAmm), amountIn);
        vm.expectRevert(bytes("REENTRANCY"));
        evilAmm.swap(address(token0), amountIn, 0);
        vm.stopPrank();
    }
}
