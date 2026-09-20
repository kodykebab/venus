"""Subscription gating via Stripe Checkout.

Deliberately not in the install path: an account starts on a trial so the
one-click install stays one click and nobody types a card number to finish
setting up. The gate applies afterwards, when the trial runs out.

Stripe is optional. With no keys configured the service runs in trial-only
mode - `configured()` is False, checkout returns None, and the dashboard says
so - rather than failing or pretending an upgrade happened.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

import httpx

import store

STRIPE_API = "https://api.stripe.com/v1"
SIGNATURE_TOLERANCE_SECONDS = 300


def configured() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY") and os.environ.get("STRIPE_PRICE_ID"))


def _secret_key() -> str:
    return os.environ["STRIPE_SECRET_KEY"]


async def create_checkout_session(
    installation_id: int,
    success_url: str,
    cancel_url: str,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Returns a hosted Checkout URL, or None when billing isn't configured.

    The installation id rides along in client_reference_id, which is what ties
    the completed payment back to the account that started it."""
    if not configured():
        return None

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        response = await client.post(
            f"{STRIPE_API}/checkout/sessions",
            auth=(_secret_key(), ""),
            data={
                "mode": "subscription",
                "line_items[0][price]": os.environ["STRIPE_PRICE_ID"],
                "line_items[0][quantity]": "1",
                "client_reference_id": str(installation_id),
                "success_url": success_url,
                "cancel_url": cancel_url,
            },
        )
        if response.status_code >= 400:
            print(f"paracheck: Stripe checkout failed ({response.status_code}): {response.text[:200]}")
            return None
        return response.json().get("url")
    finally:
        if owns_client:
            await client.aclose()


def verify_webhook_signature(payload: bytes, signature_header: str | None, now: int | None = None) -> bool:
    """Stripe's scheme: `t=<timestamp>,v1=<hmac>` over "timestamp.payload".

    The timestamp check is what stops a captured webhook being replayed later
    to re-upgrade a cancelled account."""
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret or not signature_header:
        return False

    parts = dict(
        piece.split("=", 1) for piece in signature_header.split(",") if "=" in piece
    )
    timestamp, provided = parts.get("t"), parts.get("v1")
    if not timestamp or not provided:
        return False

    try:
        age = int(now or time.time()) - int(timestamp)
    except ValueError:
        return False
    if abs(age) > SIGNATURE_TOLERANCE_SECONDS:
        return False

    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, provided)


def apply_event(event: dict) -> str | None:
    """Moves an installation between plans. Returns a short description of what
    changed, or None when the event isn't one we act on."""
    event_type = event.get("type")
    data = (event.get("data") or {}).get("object") or {}

    if event_type == "checkout.session.completed":
        installation_id = data.get("client_reference_id")
        if not installation_id:
            return None
        set_plan(int(installation_id), "pro")
        return f"installation {installation_id} upgraded to pro"

    if event_type in ("customer.subscription.deleted", "invoice.payment_failed"):
        installation_id = (data.get("metadata") or {}).get("installation_id")
        if not installation_id:
            return None
        set_plan(int(installation_id), "trial")
        return f"installation {installation_id} returned to trial"

    return None


def set_plan(installation_id: int, plan: str, db_path: str | None = None) -> None:
    with store.connect(db_path) as connection:
        connection.execute(
            "UPDATE installations SET plan = ?, updated_at = ? WHERE id = ?",
            (plan, int(time.time()), installation_id),
        )


def billing_status(installation_id: int, db_path: str | None = None) -> dict:
    installation = store.get_installation(installation_id, db_path)
    if installation is None:
        return {"plan": "unknown", "configured": configured()}
    return {
        "plan": installation["plan"],
        "trialReviewsLeft": installation["trial_reviews"],
        "configured": configured(),
    }
