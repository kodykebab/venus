"""Light coverage for the precision harness's file-walking and LOC counting.
The measurement itself is exercised by running it against real trees; here we
pin the two pure helpers that decide what gets counted."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from precision import _loc, _solidity_files


def test_skips_dependency_and_test_directories(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "A.sol").write_text("contract A {}")
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "Dep.sol").write_text("contract Dep {}")
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "A.t.sol").write_text("contract T {}")

    found = _solidity_files(str(tmp_path))
    names = [os.path.basename(p) for p in found]
    assert names == ["A.sol"], "must count only source, not deps or tests"


def test_loc_ignores_blank_and_comment_lines(tmp_path):
    f = tmp_path / "A.sol"
    f.write_text("// a comment\n\ncontract A {\n    uint256 x;\n}\n")
    # contract A, uint256 x, } => 3 code lines; comment and blank excluded.
    assert _loc(str(f)) == 3
