"""Regression coverage for run.py's path handling.

The one test here guards a bug that was as severe as this product gets: the
default-branch scan path (workflow_dispatch / the dashboard's "Scan now"
button) silently reported zero findings for any project whose contracts live
in a subdirectory - which is the common case, not an edge case. It was found
live, against this repository's own flagship demo contracts (NaiveAMM,
ShardedAMM), which have a real, reproducible hot-slot finding that simply
never appeared.

review_project() itself was never wrong and is already covered by
analyzer/static/test_review.py's own changed_files test - that test happens
to already use the correct (repo-root-relative) path format, which is exactly
why it never caught this: the bug was entirely in what run.py handed to
review_project, not in review_project's own scoping logic.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from run import rebase_to_workspace  # noqa: E402


def test_rebases_target_relative_paths_to_the_repo_root():
    # workspace/target == /repo/contracts, matching a workflow with
    # `target: contracts` - the exact configuration that shipped broken.
    root = "/repo/contracts"
    workspace = "/repo"
    scoped = ["src/NaiveAMM.sol", "src/ShardedAMM.sol"]

    assert rebase_to_workspace(scoped, root, workspace) == [
        "contracts/src/NaiveAMM.sol",
        "contracts/src/ShardedAMM.sol",
    ]


def test_is_a_no_op_when_target_is_the_repository_root():
    # `target: "."` is the other common configuration, and root == workspace
    # there - this must not add a spurious "./" prefix or otherwise disturb
    # paths that were already correct, which is why this bug went unnoticed
    # for as long as it did: every earlier test happened to use target ".".
    root = "/repo"
    workspace = "/repo"
    scoped = ["src/NaiveAMM.sol"]

    assert rebase_to_workspace(scoped, root, workspace) == ["src/NaiveAMM.sol"]


def test_handles_a_target_nested_more_than_one_level_deep():
    root = "/repo/packages/protocol/contracts"
    workspace = "/repo"
    scoped = ["Vault.sol"]

    assert rebase_to_workspace(scoped, root, workspace) == [
        "packages/protocol/contracts/Vault.sol"
    ]
