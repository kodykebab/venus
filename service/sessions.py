"""Proof that this browser installed this installation.

The dashboard is addressed by installation id, and installation ids are small
integers GitHub hands out in sequence. Without this, anyone could walk
/dashboard?installation_id=N and read other people's repository names and review
history.

There is no login to build on: the only moment we know who someone is, is the
setup callback, when GitHub has just redirected them back with a verified OAuth
code. So that moment issues a signed cookie naming the installations this
browser is entitled to see, and the dashboard checks it.

A signed cookie rather than a session table because the payload is a handful of
integers that never need revoking individually - uninstalling deactivates the
installation, which the dashboard checks anyway. If that changes, this becomes a
table and the interface stays the same.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

COOKIE_NAME = "paracheck_session"
MAX_AGE_SECONDS = 30 * 24 * 3600
MAX_INSTALLATIONS = 50  # a cookie, not a database - keep it bounded

# Generated per process when nothing is configured, which means sessions do not
# survive a restart. Fine for local development, and the alternative - a fixed
# default secret - is a forgeable cookie on every deployment that forgot to set
# one.
_EPHEMERAL_SECRET = secrets.token_bytes(32)


def _secret() -> bytes:
    """Derived from the webhook secret rather than requiring its own variable:
    one less thing to configure, and it is already required and already secret.
    Domain-separated so a session token can never be confused with anything else
    signed with the same key."""
    configured = os.environ.get("PARACHECK_SESSION_SECRET") or os.environ.get("GITHUB_WEBHOOK_SECRET")
    if not configured:
        return _EPHEMERAL_SECRET
    return hmac.new(configured.encode(), b"paracheck-session-v1", hashlib.sha256).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue(installation_ids: list[int]) -> str:
    payload = json.dumps(
        {"ids": sorted(set(installation_ids))[:MAX_INSTALLATIONS], "iat": int(time.time())},
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(_secret(), payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(signature)}"


def read(token: str | None) -> list[int]:
    """The installations this cookie proves access to. Any problem - tampered,
    malformed, expired - is the same answer: none."""
    if not token or "." not in token:
        return []

    encoded_payload, _, encoded_signature = token.partition(".")
    try:
        payload = _unb64(encoded_payload)
        signature = _unb64(encoded_signature)
    except (ValueError, TypeError):
        return []

    expected = hmac.new(_secret(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        return []

    try:
        data = json.loads(payload)
        issued_at = int(data["iat"])
        ids = [int(i) for i in data["ids"]]
    except (ValueError, KeyError, TypeError):
        return []

    if time.time() - issued_at > MAX_AGE_SECONDS:
        return []
    return ids


def grant(token: str | None, installation_id: int) -> str:
    """Adds an installation to an existing cookie. Someone who installs on their
    personal account and then on an org should not lose access to the first."""
    return issue([*read(token), installation_id])


def set_cookie(response, token: str) -> None:
    # secure=True whenever the deployment knows it is on https. Left off
    # otherwise so local http development still works.
    public_url = os.environ.get("PARACHECK_PUBLIC_URL", "")
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=MAX_AGE_SECONDS,
        httponly=True,       # nothing in the page needs to read this
        samesite="lax",      # survives GitHub's redirect back to us
        secure=public_url.startswith("https://"),
        path="/",
    )
