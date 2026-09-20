"""The sandbox exists because analyzing a pull request means running its build
system, and a build system runs whatever the repository tells it to. These
tests are written from the attacker's side: what can a postinstall script see,
and what can it do to the worker?
"""
import os
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sandbox


@pytest.fixture
def workdir():
    return tempfile.mkdtemp(prefix="sandbox-test-")


@pytest.fixture
def secrets(monkeypatch):
    for name, value in {
        "GITHUB_APP_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----",
        "GITHUB_WEBHOOK_SECRET": "webhook-secret",
        "STRIPE_SECRET_KEY": "sk_live_xxx",
        "ANTHROPIC_API_KEY": "sk-ant-xxx",
        "AWS_SECRET_ACCESS_KEY": "aws-xxx",
    }.items():
        monkeypatch.setenv(name, value)


def test_an_untrusted_child_sees_none_of_the_service_secrets(workdir, secrets):
    result = sandbox.run([sys.executable, "-c", "import os,json;print(json.dumps(dict(os.environ)))"],
                         cwd=workdir, timeout=60)
    child_env = __import__("json").loads(result.stdout)

    for leaked in ("GITHUB_APP_PRIVATE_KEY", "GITHUB_WEBHOOK_SECRET", "STRIPE_SECRET_KEY",
                   "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY"):
        assert leaked not in child_env, f"{leaked} reached an untrusted subprocess"


def test_the_allowlist_is_a_list_not_a_pattern(workdir, monkeypatch):
    """A denylist would need updating every time the deployment gains a secret.
    Anything not named is gone, however innocent it looks."""
    monkeypatch.setenv("SOME_FUTURE_CREDENTIAL", "oops")
    monkeypatch.setenv("HARMLESS_LOOKING_VAR", "also gone")
    env = sandbox.clean_environment(workdir)
    assert "SOME_FUTURE_CREDENTIAL" not in env
    assert "HARMLESS_LOOKING_VAR" not in env
    assert "PATH" in env


def test_home_points_at_the_disposable_checkout(workdir):
    env = sandbox.clean_environment(workdir)
    assert env["HOME"] == workdir
    assert env["TMPDIR"] == workdir


def test_compiler_caches_survive_the_scrub(workdir, monkeypatch):
    """Without these, forge re-downloads solc on every single review."""
    monkeypatch.setenv("SVM_ROOT", "/opt/svm")
    monkeypatch.setenv("SOLC_SELECT_DIR", "/opt/solc-select")
    env = sandbox.clean_environment(workdir)
    assert env["SVM_ROOT"] == "/opt/svm"
    assert env["SOLC_SELECT_DIR"] == "/opt/solc-select"


def test_resource_limits_reach_the_child(workdir):
    result = sandbox.run(
        [sys.executable, "-c",
         "import resource;print(resource.getrlimit(resource.RLIMIT_NPROC)[0]);"
         "print(resource.getrlimit(resource.RLIMIT_CPU)[0])"],
        cwd=workdir, timeout=60, limits={"processes": 64, "cpu_seconds": 5},
    )
    processes, cpu = result.stdout.split()
    assert int(processes) <= 64
    assert int(cpu) == 5


def test_a_timeout_takes_the_whole_process_tree(workdir):
    """start_new_session is the point: an install script that spawns a detached
    child must not outlive the review that started it."""
    with pytest.raises(subprocess.TimeoutExpired):
        sandbox.run(
            [sys.executable, "-c",
             "import subprocess,sys,time;"
             "subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)']);"
             "time.sleep(120)"],
            cwd=workdir, timeout=2,
        )


def test_a_missing_tool_reports_cleanly_instead_of_raising(workdir):
    result = sandbox.run(["definitely-not-a-real-binary"], cwd=workdir, timeout=30)
    assert result.returncode == 127
    assert "not found" in result.stderr


def test_the_in_process_scrub_restores_the_environment_even_on_failure(workdir, secrets):
    original = dict(os.environ)
    with pytest.raises(RuntimeError):
        with sandbox.scrubbed_environ(workdir):
            assert "STRIPE_SECRET_KEY" not in os.environ
            raise RuntimeError("compile blew up")
    assert os.environ["STRIPE_SECRET_KEY"] == original["STRIPE_SECRET_KEY"]
    assert dict(os.environ) == original
