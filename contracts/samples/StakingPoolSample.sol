// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Self-contained sample for ParaCheck's upload-and-analyze page
/// (demo-page/upload.html) - no imports, so it works with the single-file analyzer,
/// which doesn't resolve `import` statements. Not deployed anywhere, not part of the
/// Foundry build (lives outside contracts/src/) - purely a demo input.
///
/// Deliberately mixes both classification outcomes in one contract:
/// - `stake` / `unstake` both touch `totalStaked`, a single shared counter -> HOT.
/// - `claimReward` only touches `rewards[msg.sender]`, a per-caller mapping slot,
///   and never touches `totalStaked` -> SAFE. Expect a parallelism score around 33
///   (1 of 3 state-changing functions clean), flags on `totalStaked`, and
///   `claimReward` listed under safe functions.
contract StakingPoolSample {
    mapping(address => uint256) public staked;
    mapping(address => uint256) public rewards;
    uint256 public totalStaked;

    event Staked(address indexed user, uint256 amount);
    event Unstaked(address indexed user, uint256 amount);
    event RewardClaimed(address indexed user, uint256 amount);

    function stake() external payable {
        require(msg.value > 0, "ZERO_AMOUNT");
        staked[msg.sender] += msg.value;
        totalStaked += msg.value;
        emit Staked(msg.sender, msg.value);
    }

    function unstake(uint256 amount) external {
        require(staked[msg.sender] >= amount, "INSUFFICIENT_STAKE");
        staked[msg.sender] -= amount;
        totalStaked -= amount;
        payable(msg.sender).transfer(amount);
        emit Unstaked(msg.sender, amount);
    }

    function claimReward() external {
        uint256 amount = rewards[msg.sender];
        rewards[msg.sender] = 0;
        payable(msg.sender).transfer(amount);
        emit RewardClaimed(msg.sender, amount);
    }
}
