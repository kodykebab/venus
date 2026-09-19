// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Common external interface shared by NaiveAMM and ShardedAMM so that a caller
/// (or the ParaCheck demo/load tooling) can interact with either implementation identically.
interface IAMM {
    event LiquidityAdded(address indexed provider, uint256 amount0, uint256 amount1);
    event Swap(address indexed trader, address indexed tokenIn, uint256 amountIn, uint256 amountOut);

    function token0() external view returns (address);
    function token1() external view returns (address);

    function addLiquidity(uint256 amount0, uint256 amount1) external;

    function swap(address tokenIn, uint256 amountIn, uint256 minAmountOut) external returns (uint256 amountOut);

    function getReserves() external view returns (uint256 reserve0, uint256 reserve1);
}
