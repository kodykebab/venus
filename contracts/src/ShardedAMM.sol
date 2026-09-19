// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IAMM} from "./interfaces/IAMM.sol";
import {IERC20} from "./interfaces/IERC20.sol";

/// @notice Constant-product AMM with an identical external interface/behavior to NaiveAMM,
/// but reserves are sharded across `bandCount` independent price bands selected by swap
/// size. swap() only reads/writes the two storage slots of its own band, so concurrent
/// swaps landing in different bands touch disjoint slots and don't conflict under
/// optimistic parallel execution.
///
/// Band selection by amountIn size is a simplified, parameterized illustrative model —
/// not production-grade concentrated-liquidity math.
contract ShardedAMM is IAMM {
    uint256 public constant FEE_BPS = 30; // 0.30%
    uint256 private constant BPS_DENOM = 10_000;

    address public immutable token0;
    address public immutable token1;
    uint256 public immutable bandCount;
    uint256 public immutable bandWidth;

    mapping(uint256 => uint256) public reserve0ByBand;
    mapping(uint256 => uint256) public reserve1ByBand;

    uint256 private _locked = 1;

    modifier nonReentrant() {
        require(_locked == 1, "REENTRANCY");
        _locked = 2;
        _;
        _locked = 1;
    }

    constructor(address token0_, address token1_, uint256 bandCount_, uint256 bandWidth_) {
        require(token0_ != address(0) && token1_ != address(0), "ZERO_ADDRESS");
        require(token0_ != token1_, "IDENTICAL_TOKENS");
        require(bandCount_ > 0, "ZERO_BAND_COUNT");
        require(bandWidth_ > 0, "ZERO_BAND_WIDTH");

        token0 = token0_;
        token1 = token1_;
        bandCount = bandCount_;
        bandWidth = bandWidth_;
    }

    /// @dev Liquidity is split evenly across all bands (remainder goes to band 0) so every
    /// band has usable reserves from the start.
    function addLiquidity(uint256 amount0, uint256 amount1) external nonReentrant {
        require(amount0 > 0 && amount1 > 0, "ZERO_AMOUNT");
        require(IERC20(token0).transferFrom(msg.sender, address(this), amount0), "TRANSFER_FAILED");
        require(IERC20(token1).transferFrom(msg.sender, address(this), amount1), "TRANSFER_FAILED");

        uint256 share0 = amount0 / bandCount;
        uint256 share1 = amount1 / bandCount;

        for (uint256 i = 0; i < bandCount; i++) {
            reserve0ByBand[i] += share0;
            reserve1ByBand[i] += share1;
        }
        reserve0ByBand[0] += amount0 - (share0 * bandCount);
        reserve1ByBand[0] += amount1 - (share1 * bandCount);

        emit LiquidityAdded(msg.sender, amount0, amount1);
    }

    function swap(address tokenIn, uint256 amountIn, uint256 minAmountOut)
        external
        nonReentrant
        returns (uint256 amountOut)
    {
        require(amountIn > 0, "ZERO_AMOUNT");
        require(tokenIn == token0 || tokenIn == token1, "INVALID_TOKEN");

        uint256 band = bandOf(amountIn);
        bool zeroForOne = tokenIn == token0;
        (uint256 reserveIn, uint256 reserveOut) = zeroForOne
            ? (reserve0ByBand[band], reserve1ByBand[band])
            : (reserve1ByBand[band], reserve0ByBand[band]);
        require(reserveIn > 0 && reserveOut > 0, "NO_LIQUIDITY");

        amountOut = _getAmountOut(amountIn, reserveIn, reserveOut);
        require(amountOut > 0 && amountOut >= minAmountOut, "SLIPPAGE");

        address tokenOut = zeroForOne ? token1 : token0;

        require(IERC20(tokenIn).transferFrom(msg.sender, address(this), amountIn), "TRANSFER_FAILED");

        if (zeroForOne) {
            reserve0ByBand[band] = reserveIn + amountIn;
            reserve1ByBand[band] = reserveOut - amountOut;
        } else {
            reserve1ByBand[band] = reserveIn + amountIn;
            reserve0ByBand[band] = reserveOut - amountOut;
        }

        require(IERC20(tokenOut).transfer(msg.sender, amountOut), "TRANSFER_FAILED");

        emit Swap(msg.sender, tokenIn, amountIn, amountOut);
    }

    /// @notice Which band a swap of this size routes to. Public so tests, the static/dynamic
    /// analyzers, and the demo page can all agree on band assignment without duplicating logic.
    function bandOf(uint256 amountIn) public view returns (uint256) {
        return (amountIn / bandWidth) % bandCount;
    }

    function getReserves() external view returns (uint256 reserve0, uint256 reserve1) {
        for (uint256 i = 0; i < bandCount; i++) {
            reserve0 += reserve0ByBand[i];
            reserve1 += reserve1ByBand[i];
        }
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
