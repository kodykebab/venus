"""GitHub App authentication: App JWT -> per-installation access token.

Three credentials matter here and none of them may ever be logged or persisted
in plaintext: the App's private key (signs the JWT proving we are the App), the
webhook secret (verifies inbound payloads), and the OAuth client secret
(exchanges an install `code` for a user token). All three come from the
environment.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass

import httpx
import jwt

GITHUB_API = "https://api.github.com"
API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


class ConfigurationError(RuntimeError):
    """A required GitHub App credential is missing."""


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigurationError(f"{name} is not set")
    return value


def app_id() -> str:
    return _require("GITHUB_APP_ID")


def private_key() -> str:
    """The App's PEM. Supports either an inline value or a path, because secret
    managers and local dev disagree about which is convenient."""
    inline = os.environ.get("GITHUB_APP_PRIVATE_KEY")
    if inline:
        return inline.replace("\\n", "\n")
    path = _require("GITHUB_APP_PRIVATE_KEY_PATH")
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def app_jwt(now: int | None = None) -> str:
    """Short-lived JWT authenticating as the App itself. Backdated 60s because
    GitHub rejects tokens whose iat is even slightly in its future."""
    issued = int(now or time.time()) - 60
    return jwt.encode(
        {"iat": issued, "exp": issued + 540, "iss": app_id()},
        private_key(),
        algorithm="RS256",
    )


@dataclass
class InstallationToken:
    # Opaque by contract. GitHub's stateless token format is not a fixed length,
    # so nothing here may validate, truncate, or pattern-match on the value.
    token: str
    expires_at: str

    @property
    def headers(self) -> dict[str, str]:
        return {**API_HEADERS, "Authorization": f"Bearer {self.token}"}


async def installation_token(installation_id: int, client: httpx.AsyncClient | None = None) -> InstallationToken:
    """Mints a fresh installation token. These expire in about an hour - always
    fetch per job rather than caching one for reuse."""
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        response = await client.post(
            f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers={**API_HEADERS, "Authorization": f"Bearer {app_jwt()}"},
        )
        response.raise_for_status()
        payload = response.json()
        return InstallationToken(token=payload["token"], expires_at=payload.get("expires_at", ""))
    finally:
        if owns_client:
            await client.aclose()


def verify_webhook_signature(body: bytes, signature_header: str | None) -> bool:
    """Constant-time HMAC check. An unsigned or mismatched payload is rejected
    before anything in it is parsed or trusted."""
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
    if not secret or not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header[len("sha256="):])


async def exchange_oauth_code(code: str, client: httpx.AsyncClient | None = None) -> dict:
    """Trades the `code` GitHub sends to the Setup URL for a user access token.
    This is what makes install-and-login a single click."""
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        response = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": _require("GITHUB_CLIENT_ID"),
                "client_secret": _require("GITHUB_CLIENT_SECRET"),
                "code": code,
            },
        )
        response.raise_for_status()
        return response.json()
    finally:
        if owns_client:
            await client.aclose()


async def authenticated_user(user_token: str, client: httpx.AsyncClient | None = None) -> dict:
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        response = await client.get(
            f"{GITHUB_API}/user",
            headers={**API_HEADERS, "Authorization": f"Bearer {user_token}"},
        )
        response.raise_for_status()
        return response.json()
    finally:
        if owns_client:
            await client.aclose()
