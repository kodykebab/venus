// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IAMM} from "./interfaces/IAMM.sol";
import {IERC20} from "./interfaces/IERC20.sol";

/// @notice Minimal constant-product AMM with a single global reserve0/reserve1 pair.
/// Every swap() reads and writes the same two storage slots, so any two concurrent
/// swaps in the same block touch the same slots and conflict under optimistic
/// parallel execution — this is the "naive" contrast case for ParaCheck's ShardedAMM.
contract NaiveAMM is IAMM {
    uint256 public constant FEE_BPS = 30; // 0.30%
    uint256 private constant BPS_DENOM = 10_000;

    address public immutable token0;
    address public immutable token1;

    uint256 public reserve0;
    uint256 public reserve1;

    uint256 private _locked = 1;

    modifier nonReentrant() {
        require(_locked == 1, "REENTRANCY");
        _locked = 2;
        _;
        _locked = 1;
    }

    constructor(address token0_, address token1_) {
        require(token0_ != address(0) && token1_ != address(0), "ZERO_ADDRESS");
        require(token0_ != token1_, "IDENTICAL_TOKENS");
        token0 = token0_;
        token1 = token1_;
    }

    function addLiquidity(uint256 amount0, uint256 amount1) external nonReentrant {
        require(amount0 > 0 && amount1 > 0, "ZERO_AMOUNT");
        require(IERC20(token0).transferFrom(msg.sender, address(this), amount0), "TRANSFER_FAILED");
        require(IERC20(token1).transferFrom(msg.sender, address(this), amount1), "TRANSFER_FAILED");

        reserve0 += amount0;
        reserve1 += amount1;

        emit LiquidityAdded(msg.sender, amount0, amount1);
    }

    function swap(address tokenIn, uint256 amountIn, uint256 minAmountOut)
        external
        nonReentrant
        returns (uint256 amountOut)
    {
        require(amountIn > 0, "ZERO_AMOUNT");
        require(tokenIn == token0 || tokenIn == token1, "INVALID_TOKEN");

        bool zeroForOne = tokenIn == token0;
        (uint256 reserveIn, uint256 reserveOut) = zeroForOne ? (reserve0, reserve1) : (reserve1, reserve0);
        require(reserveIn > 0 && reserveOut > 0, "NO_LIQUIDITY");

        amountOut = _getAmountOut(amountIn, reserveIn, reserveOut);
        require(amountOut > 0 && amountOut >= minAmountOut, "SLIPPAGE");

        address tokenOut = zeroForOne ? token1 : token0;

        require(IERC20(tokenIn).transferFrom(msg.sender, address(this), amountIn), "TRANSFER_FAILED");

        if (zeroForOne) {
            reserve0 = reserveIn + amountIn;
            reserve1 = reserveOut - amountOut;
        } else {
            reserve1 = reserveIn + amountIn;
            reserve0 = reserveOut - amountOut;
        }

        require(IERC20(tokenOut).transfer(msg.sender, amountOut), "TRANSFER_FAILED");

        emit Swap(msg.sender, tokenIn, amountIn, amountOut);
    }

    function getReserves() external view returns (uint256, uint256) {
        return (reserve0, reserve1);
    }

    function _getAmountOut(uint256 amountIn, uint256 reserveIn, uint256 reserveOut)
        private
        pure
        returns (uint256)
    {
        uint256 amountInWithFee = amountIn * (BPS_DENOM - FEE_BPS);
        uint256 numerator = amountInWithFee * reserveOut;
        uint256 denominator = (reserveIn * BPS_DENOM) + amountInWithFee;
        return numerator / denominator;
    }
}
