"""`paracheck doctor --service` - is this deployment actually able to run?

Every one of these fails late and quietly if it's wrong. A malformed private key
surfaces as reviews that never appear, because minting an installation token
fails inside a background job. A missing webhook secret means every delivery is
rejected with a 401 GitHub shows only in its own delivery log. A missing
encryption secret means the key someone pastes has nowhere safe to go.

So they're checked at once, by name, with the consequence of each spelled out -
and the optional ones are clearly marked, because most of this is optional and a
deployment that only wants free reviews should not be told it's broken.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OK, WARN, FAIL = "ok", "warn", "fail"
MARKS = {OK: "✓", WARN: "!", FAIL: "✗"}


class Check:
    def __init__(self, name: str, status: str, detail: str, fix: str = "") -> None:
        self.name, self.status, self.detail, self.fix = name, status, detail, fix

    def as_dict(self) -> dict:
        return {"check": self.name, "status": self.status, "detail": self.detail, "fix": self.fix}


def _present(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def check_app_id() -> Check:
    value = os.environ.get("GITHUB_APP_ID", "").strip()
    if not value:
        return Check("GITHUB_APP_ID", FAIL, "not set - no reviews can be posted",
                     "the number at the top of your App's settings page")
    if not value.isdigit():
        return Check("GITHUB_APP_ID", FAIL, f"{value!r} is not a number - this is the App ID, "
                     "not the client id or the slug", "use the numeric App ID")
    return Check("GITHUB_APP_ID", OK, value)


def check_private_key() -> Check:
    """Parsed, not just present: a key mangled by a shell or a secrets UI that
    stripped its newlines looks set and fails at the first token mint."""
    pem = os.environ.get("GITHUB_APP_PRIVATE_KEY", "")
    if not pem.strip():
        return Check("GITHUB_APP_PRIVATE_KEY", FAIL, "not set - no reviews can be posted",
                     "set it with your deployment provider's secret manager from the PEM file")
    if "BEGIN" not in pem:
        return Check("GITHUB_APP_PRIVATE_KEY", FAIL, "does not look like a PEM file",
                     "paste the whole .pem, including the BEGIN/END lines")
    if "\\n" in pem and "\n" not in pem:
        return Check("GITHUB_APP_PRIVATE_KEY", FAIL,
                     "newlines are escaped as literal backslash-n",
                     "set it from the file directly rather than pasting one line")
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        load_pem_private_key(pem.encode(), password=None)
    except Exception as exc:  # noqa: BLE001 - any parse failure is the same answer
        return Check("GITHUB_APP_PRIVATE_KEY", FAIL, f"present but unreadable: {type(exc).__name__}",
                     "regenerate the key on the App's settings page")
    return Check("GITHUB_APP_PRIVATE_KEY", OK, "parses as a private key")


def check_webhook_secret() -> Check:
    if not _present("GITHUB_WEBHOOK_SECRET"):
        return Check("GITHUB_WEBHOOK_SECRET", FAIL,
                     "not set - every webhook will be rejected as unsigned",
                     "set the same value here and in the App's webhook settings")
    return Check("GITHUB_WEBHOOK_SECRET", OK, "set")


def check_oauth() -> Check:
    have = [n for n in ("GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET") if _present(n)]
    if len(have) == 2:
        return Check("GITHUB_CLIENT_ID/SECRET", OK, "set")
    if not have:
        return Check("GITHUB_CLIENT_ID/SECRET", WARN,
                     "not set - installs work, but accounts show as 'unknown'",
                     "from the same App settings page, under Client secrets")
    return Check("GITHUB_CLIENT_ID/SECRET", FAIL, f"only {have[0]} is set - set both or neither",
                 "an OAuth exchange needs both halves")


def check_public_url() -> Check:
    url = os.environ.get("PARACHECK_PUBLIC_URL", "").strip()
    if not url:
        return Check("PARACHECK_PUBLIC_URL", WARN,
                     "not set - callback URLs are guessed from the request, and session "
                     "cookies won't be marked Secure",
                     "set it to your deployed https:// URL")
    if not url.startswith("https://"):
        return Check("PARACHECK_PUBLIC_URL", WARN, f"{url} is not https - cookies won't be Secure",
                     "use the https:// URL in production")
    return Check("PARACHECK_PUBLIC_URL", OK, url)


def check_encryption() -> Check:
    import secrets_store

    if not secrets_store.available():
        return Check("key encryption", FAIL,
                     "no encryption secret - installations cannot supply their own API key",
                     "set PARACHECK_ENCRYPTION_KEY (GITHUB_WEBHOOK_SECRET is used if unset)")
    if _present("PARACHECK_ENCRYPTION_KEY"):
        return Check("key encryption", OK, "using PARACHECK_ENCRYPTION_KEY")
    return Check("key encryption", OK, "derived from GITHUB_WEBHOOK_SECRET")


def check_database() -> Check:
    import store

    path = store.DEFAULT_DB_PATH
    try:
        store.init_db()
    except Exception as exc:  # noqa: BLE001
        return Check("database", FAIL, f"{path} is not writable: {exc}",
                     "mount a volume there, or set PARACHECK_DB somewhere writable")

    directory = os.path.dirname(os.path.abspath(path))
    if directory == "/app" or not os.path.isdir(directory):
        return Check("database", WARN, f"{path} is not on a mounted volume - it will be lost "
                     "on redeploy", "set PARACHECK_DB to a path on a persistent volume")
    return Check("database", OK, path)


def check_fallback_key() -> Check:
    """Optional by design: installations bring their own. A deployment key is
    the single-tenant shortcut."""
    if _present("ANTHROPIC_API_KEY"):
        return Check("ANTHROPIC_API_KEY", OK, "set - used when an installation has no key of its own")
    return Check("ANTHROPIC_API_KEY", WARN,
                 "not set - installations without their own key get reviews rendered "
                 "from findings, with no written summary",
                 "optional: set one to cover every installation from this deployment")


def check_billing() -> Check:
    import billing

    if billing.configured():
        missing = [n for n in ("STRIPE_WEBHOOK_SECRET",) if not _present(n)]
        if missing:
            return Check("stripe", FAIL, f"checkout is configured but {missing[0]} is not - "
                         "subscriptions will never activate",
                         "set it from the Stripe webhook endpoint you created")
        return Check("stripe", OK, "subscriptions enabled")
    return Check("stripe", FAIL, "not configured - paid reviews cannot start",
                 "set STRIPE_SECRET_KEY, STRIPE_HOBBY_PRICE_ID, STRIPE_PRO_PRICE_ID and STRIPE_WEBHOOK_SECRET")


def check_clerk() -> Check:
    publishable = _present("CLERK_PUBLISHABLE_KEY")
    verification = _present("CLERK_JWT_KEY")
    if publishable and verification:
        return Check("clerk", OK, "account sign-in enabled")
    if not publishable and not verification:
        return Check("clerk", WARN, "not configured - direct GitHub-session checkout remains available",
                     "set CLERK_PUBLISHABLE_KEY and CLERK_JWT_KEY for account checkout")
    return Check("clerk", FAIL, "only one Clerk credential is set - checkout sign-in will fail",
                 "set both CLERK_PUBLISHABLE_KEY and CLERK_JWT_KEY")


def run_checks() -> list[Check]:
    return [
        check_app_id(),
        check_private_key(),
        check_webhook_secret(),
        check_oauth(),
        check_public_url(),
        check_encryption(),
        check_database(),
        check_fallback_key(),
        check_billing(),
        check_clerk(),
    ]


def render(checks: list[Check]) -> str:
    width = max(len(c.name) for c in checks)
    lines = []
    for check in checks:
        lines.append(f"  {MARKS[check.status]} {check.name.ljust(width)}  {check.detail}")
        if check.fix and check.status != OK:
            lines.append(f"    {' ' * width}  -> {check.fix}")

    failures = [c for c in checks if c.status == FAIL]
    lines.append("")
    if failures:
        lines.append(f"{len(failures)} blocking problem(s): this deployment cannot review "
                     "pull requests yet.")
    else:
        optional = len([c for c in checks if c.status == WARN])
        lines.append("Ready to review pull requests."
                     + (f" {optional} optional feature(s) not configured." if optional else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    checks = run_checks()
    if "--json" in argv:
        print(json.dumps({"checks": [c.as_dict() for c in checks]}, indent=2))
    else:
        print("paracheck doctor --service\n")
        print(render(checks))
    return 1 if any(c.status == FAIL for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
