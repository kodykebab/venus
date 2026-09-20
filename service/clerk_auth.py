"""Small Clerk session-token verifier for the paid account flow.

Clerk authenticates the person; GitHub installation sessions still authorize
which repositories that person may manage. The browser only receives the
publishable key. Verification happens here with Clerk's JWT verification key.
"""
from __future__ import annotations

import os

import jwt
from fastapi import Request


def configured() -> bool:
    return bool(os.environ.get("CLERK_PUBLISHABLE_KEY") and os.environ.get("CLERK_JWT_KEY"))


def publishable_key() -> str:
    return os.environ.get("CLERK_PUBLISHABLE_KEY", "")


def user_id(request: Request) -> str | None:
    """Return the verified Clerk subject from an Authorization bearer token."""
    if not configured():
        return None
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None

    options = {"require": ["sub", "exp", "iat"]}
    kwargs = {"algorithms": ["RS256"], "options": options}
    issuer = os.environ.get("CLERK_ISSUER")
    audience = os.environ.get("CLERK_AUDIENCE")
    if issuer:
        kwargs["issuer"] = issuer
    if audience:
        kwargs["audience"] = audience
    key = os.environ["CLERK_JWT_KEY"].replace("\\n", "\n")
    try:
        claims = jwt.decode(token, key, **kwargs)
    except jwt.PyJWTError:
        return None
    subject = claims.get("sub")
    return subject if isinstance(subject, str) and subject else None