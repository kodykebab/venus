// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ShardedAMM} from "../src/ShardedAMM.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {MaliciousReentrantToken} from "./mocks/MaliciousReentrantToken.sol";

contract ShardedAMMTest is Test {
    ShardedAMM amm;
    MockERC20 token0;
    MockERC20 token1;

    address lp = makeAddr("lp");
    address trader = makeAddr("trader");

    uint256 constant BAND_COUNT = 3;
    uint256 constant BAND_WIDTH = 1_000e18;
    uint256 constant INITIAL_LIQUIDITY = 3_000_000e18; // divisible by BAND_COUNT

    function setUp() public {
        token0 = new MockERC20("Token0", "TK0");
        token1 = new MockERC20("Token1", "TK1");
        amm = new ShardedAMM(address(token0), address(token1), BAND_COUNT, BAND_WIDTH);

        token0.mint(lp, INITIAL_LIQUIDITY);
        token1.mint(lp, INITIAL_LIQUIDITY);

        vm.startPrank(lp);
        token0.approve(address(amm), type(uint256).max);
        token1.approve(address(amm), type(uint256).max);
        amm.addLiquidity(INITIAL_LIQUIDITY, INITIAL_LIQUIDITY);
        vm.stopPrank();
    }

    function test_Constructor_RevertsOnZeroBandCount() public {
        vm.expectRevert(bytes("ZERO_BAND_COUNT"));
        new ShardedAMM(address(token0), address(token1), 0, BAND_WIDTH);
    }

    function test_Constructor_RevertsOnZeroBandWidth() public {
        vm.expectRevert(bytes("ZERO_BAND_WIDTH"));
        new ShardedAMM(address(token0), address(token1), BAND_COUNT, 0);
    }

    function test_AddLiquidity_SplitsAcrossBands() public view {
        uint256 expectedPerBand = INITIAL_LIQUIDITY / BAND_COUNT;
        for (uint256 i = 0; i < BAND_COUNT; i++) {
            assertEq(amm.reserve0ByBand(i), expectedPerBand);
            assertEq(amm.reserve1ByBand(i), expectedPerBand);
        }
        (uint256 r0, uint256 r1) = amm.getReserves();
        assertEq(r0, INITIAL_LIQUIDITY);
        assertEq(r1, INITIAL_LIQUIDITY);
    }

    function test_BandOf_MatchesFormula() public view {
        // amountIn = 2 * BAND_WIDTH + 500 -> band index 2 (with BAND_COUNT=3, no wraparound)
        uint256 amountIn = 2 * BAND_WIDTH + 500;
        assertEq(amm.bandOf(amountIn), 2);
    }

    function test_BandOf_BoundaryExactMultiple() public view {
        // Exactly on a band boundary: amountIn == BAND_WIDTH must land in band 1, not band 0.
        assertEq(amm.bandOf(BAND_WIDTH), 1);
        // One wei below the boundary still belongs to band 0.
        assertEq(amm.bandOf(BAND_WIDTH - 1), 0);
    }

    function test_BandOf_WrapsAroundBandCount() public view {
        // BAND_COUNT bands worth of width wraps back to band 0.
        assertEq(amm.bandOf(BAND_WIDTH * BAND_COUNT), 0);
    }

    function test_Swap_DifferentBandsTouchDisjointSlots() public {
        uint256 amountInBand0 = 500e18; // band 0
        uint256 amountInBand1 = BAND_WIDTH + 500e18; // band 1

        token0.mint(trader, amountInBand0 + amountInBand1);
        vm.startPrank(trader);
        token0.approve(address(amm), amountInBand0 + amountInBand1);

        uint256 band0ReserveBefore = amm.reserve0ByBand(0);
        uint256 band1ReserveBefore = amm.reserve0ByBand(1);

        amm.swap(address(token0), amountInBand0, 0);
        assertEq(amm.reserve0ByBand(0), band0ReserveBefore + amountInBand0);
        assertEq(amm.reserve0ByBand(1), band1ReserveBefore, "band 1 must be untouched by a band-0 swap");

        amm.swap(address(token0), amountInBand1, 0);
        assertEq(amm.reserve0ByBand(1), band1ReserveBefore + amountInBand1);

        vm.stopPrank();
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

    function test_RevertWhen_ReentrantSwap() public {
        MaliciousReentrantToken evilToken1 = new MaliciousReentrantToken();
        ShardedAMM evilAmm = new ShardedAMM(address(token0), address(evilToken1), BAND_COUNT, BAND_WIDTH);

        token0.mint(lp, INITIAL_LIQUIDITY);
        evilToken1.mint(lp, INITIAL_LIQUIDITY);
        vm.startPrank(lp);
        token0.approve(address(evilAmm), type(uint256).max);
        evilToken1.approve(address(evilAmm), type(uint256).max);
        evilAmm.addLiquidity(INITIAL_LIQUIDITY, INITIAL_LIQUIDITY);
        vm.stopPrank();

        evilToken1.setAttack(evilAmm, address(token0));

        uint256 amountIn = 500e18;
        token0.mint(trader, amountIn);
        vm.startPrank(trader);
        token0.approve(address(evilAmm), amountIn);
        vm.expectRevert(bytes("REENTRANCY"));
        evilAmm.swap(address(token0), amountIn, 0);
        vm.stopPrank();
    }
}
