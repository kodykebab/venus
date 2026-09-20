"""Runs third-party build tooling as if it were hostile, because it is.

Analyzing a pull request means running `forge install` and `npm install` on code
somebody else wrote. Both execute arbitrary code by design - git hooks, npm
postinstall scripts - so any subprocess started while a repository is checked
out should be assumed to be attacker-controlled.

Two things are enforced here:

1. **A scrubbed environment.** A child process inherits os.environ by default,
   which on the CI service holds the GitHub App private key, the Stripe secret
   and the Anthropic key. A postinstall script that reads os.environ and POSTs
   it somewhere would own every installation. Children get an explicit
   allowlist instead - never a denylist, because the next secret added to the
   deployment would silently not be on it.

2. **Kernel resource limits.** A timeout alone doesn't stop a fork bomb, a
   memory balloon or a disk filler from taking the worker down with it.

Limits are applied by re-executing through this module's __main__ rather than
with preexec_fn: preexec_fn runs Python between fork and exec, which is not safe
in a process running jobs on threads (it can deadlock on a lock held by another
thread at fork time), and the worker does exactly that.
"""
from __future__ import annotations

import json
import os
import resource
import subprocess
import sys

# Everything a compiler toolchain legitimately needs, and nothing else. PATH is
# passed through because forge/npm/solc have to be findable, and the compiler
# cache locations are passed explicitly (SVM_ROOT, SOLC_SELECT_DIR) because HOME
# is redirected below - without them forge would re-download solc every review.
ENV_ALLOWLIST = (
    "PATH",
    "LANG",
    "LC_ALL",
    "TZ",
    "TERM",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "SOLC_VERSION",
    "SOLC_SELECT_DIR",
    "SVM_ROOT",
    "VIRTUAL_ENV",
    "FOUNDRY_DISABLE_NIGHTLY_WARNING",
)

DEFAULT_LIMITS = {
    "cpu_seconds": 900,
    "memory_bytes": 4 * 1024 * 1024 * 1024,
    "file_bytes": 2 * 1024 * 1024 * 1024,
    "processes": 512,  # enough for a parallel build, far short of a fork bomb
}


def clean_environment(home: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment an untrusted child gets: the allowlist, plus a HOME it is
    welcome to write to.

    HOME points at the disposable checkout rather than the worker's real home:
    npm and forge both want a writable HOME, and a postinstall script that can
    write to ~/.foundry could poison the toolchain for every later review."""
    env = {key: os.environ[key] for key in ENV_ALLOWLIST if key in os.environ}
    env["HOME"] = home
    env["TMPDIR"] = home
    # npm phones home and writes funding/audit noise otherwise; both are network
    # calls we neither need nor want from inside a review.
    env.setdefault("NPM_CONFIG_UPDATE_NOTIFIER", "false")
    env.setdefault("NPM_CONFIG_FUND", "false")
    env.setdefault("NPM_CONFIG_AUDIT", "false")
    env.setdefault("CI", "true")
    if extra:
        env.update(extra)
    return env


def apply_limits(limits: dict[str, int]) -> None:
    """Applies rlimits to the current process. Only ever called in a child that
    is about to exec - never in the worker itself."""
    def limit(kind: int, value: int) -> None:
        try:
            soft, hard = resource.getrlimit(kind)
            ceiling = value if hard == resource.RLIM_INFINITY else min(value, hard)
            resource.setrlimit(kind, (ceiling, hard))
        except (ValueError, OSError):
            pass  # a platform without this limit shouldn't stop the review

    limit(resource.RLIMIT_CPU, limits["cpu_seconds"])
    limit(resource.RLIMIT_FSIZE, limits["file_bytes"])
    limit(resource.RLIMIT_NPROC, limits["processes"])
    if hasattr(resource, "RLIMIT_AS") and sys.platform != "darwin":
        # RLIMIT_AS on macOS breaks anything that reserves large virtual
        # mappings (the JVM, Node, jemalloc) even when it never touches them.
        limit(resource.RLIMIT_AS, limits["memory_bytes"])


def run(
    command: list[str],
    cwd: str,
    timeout: int,
    home: str | None = None,
    limits: dict[str, int] | None = None,
) -> subprocess.CompletedProcess:
    """Runs `command` with a scrubbed environment and resource limits.

    start_new_session puts the child in its own process group, so a timeout
    kills the whole tree rather than orphaning the grandchildren an install
    script spawned."""
    effective = {**DEFAULT_LIMITS, **(limits or {})}
    return subprocess.run(
        [sys.executable, os.path.abspath(__file__), json.dumps(effective), "--", *command],
        cwd=cwd,
        env=clean_environment(home or cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        start_new_session=True,
    )


class scrubbed_environ:
    """Scrubs os.environ in-process, for libraries that spawn their own children.

    crytic-compile shells out to `forge build` itself, so there is no argv for
    sandbox.run() to wrap - the only place to intervene is the environment those
    children inherit. Restores the original on exit, including on exception.
    """

    def __init__(self, home: str, extra: dict[str, str] | None = None) -> None:
        self._replacement = clean_environment(home, extra)
        self._saved: dict[str, str] = {}

    def __enter__(self) -> "scrubbed_environ":
        self._saved = dict(os.environ)
        os.environ.clear()
        os.environ.update(self._replacement)
        return self

    def __exit__(self, *_exc) -> None:
        os.environ.clear()
        os.environ.update(self._saved)


def main() -> None:
    """Re-exec shim: apply limits, then become the requested command."""
    limits = json.loads(sys.argv[1])
    command = sys.argv[sys.argv.index("--") + 1:]
    apply_limits(limits)
    try:
        os.execvp(command[0], command)
    except FileNotFoundError:
        sys.stderr.write(f"{command[0]}: not found\n")
        raise SystemExit(127)


if __name__ == "__main__":
    main()
