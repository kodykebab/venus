"""Paid plan gating via Stripe Checkout.

New installations are unpaid until a Hobby or Pro Checkout completes. There
is no free entitlement and every paid plan has an explicit review quota.
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
# Quotas are per rolling 7-day window (see store.QUOTA_WINDOW_SECONDS), not per
# billing period: a review compiles and analyses an arbitrary repository, so the
# cost is in CPU and minutes, and it has to be bounded at the rate it is
# incurred. These numbers are the single source of truth - the pricing page, the
# dashboard and the check-run messages all read them from here, so they cannot
# drift apart.
PLANS = {
    "hobby": {
        "price_env": "STRIPE_HOBBY_PRICE_ID",
        "review_limit": 20,
        "label": "Hobby",
        "price": "$9",
        "cadence": "/month",
        "blurb": "For a developer keeping one or two contracts honest.",
        "features": [
            "20 scans per week",
            "GitHub PR Check Runs and inline annotations",
            "Static analysis: Slither + hot-slot classifier",
            "Dynamic contention analysis",
        ],
    },
    "pro": {
        "price_env": "STRIPE_PRO_PRICE_ID",
        "review_limit": 100,
        "label": "Pro",
        "price": "$29",
        "cadence": "/month",
        "blurb": "For a team shipping to a parallel-execution chain.",
        "features": [
            "100 scans per week",
            "Everything in Hobby",
            "Unlimited repositories per installation",
            "Merge gating on severity thresholds",
        ],
    },
}

# Enterprise is sales-led and has no Stripe price: quota is agreed in the
# contract, so review_limit is None rather than a number we invented.
ENTERPRISE = {
    "label": "Enterprise",
    "review_limit": None,
    "price": "Custom",
    "cadence": "",
    "blurb": "For protocols with their own volume, deployment and support needs.",
    "features": [
        "Custom weekly scan quota",
        "Everything in Pro",
        "Self-hosted or dedicated deployment options",
        "Direct support channel",
    ],
}


def review_limit(plan: str) -> int | None:
    """Scans permitted per rolling week. None means "no fixed cap" and is only
    ever enterprise; an unknown or unpaid plan is 0, not unlimited."""
    if plan == "enterprise":
        return None
    details = PLANS.get(plan)
    return details["review_limit"] if details else 0


def plan_details(plan: str) -> dict | None:
    if plan == "enterprise":
        return dict(ENTERPRISE)
    details = PLANS.get(plan)
    if details is None:
        return None
    # An override exists so a deployment can run a promotion without a code
    # change, but the default is the published price.
    return {**details, "price": os.environ.get(
        f"PARACHECK_{plan.upper()}_PRICE", details["price"]
    )}


def configured() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY") and all(
        os.environ.get(details["price_env"]) for details in PLANS.values()
    ))


def _secret_key() -> str:
    return os.environ["STRIPE_SECRET_KEY"]


async def create_checkout_session(
    installation_id: int,
    plan: str,
    success_url: str,
    cancel_url: str,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Returns a hosted Checkout URL, or None when billing isn't configured.

    The installation id rides along in client_reference_id, which is what ties
    the completed payment back to the account that started it."""
    details = plan_details(plan)
    price_id = os.environ.get(details["price_env"]) if details else None
    if not os.environ.get("STRIPE_SECRET_KEY") or not price_id:
        return None

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        response = await client.post(
            f"{STRIPE_API}/checkout/sessions",
            auth=(_secret_key(), ""),
            data={
                "mode": "subscription",
                "line_items[0][price]": price_id,
                "line_items[0][quantity]": "1",
                "client_reference_id": str(installation_id),
                "metadata[installation_id]": str(installation_id),
                "metadata[plan]": plan,
                "subscription_data[metadata][installation_id]": str(installation_id),
                "subscription_data[metadata][plan]": plan,
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
        plan = data.get("metadata", {}).get("plan", "pro")
        if plan not in PLANS:
            return None
        set_plan(int(installation_id), plan)
        return f"installation {installation_id} upgraded to {plan}"

    # A renewal re-asserts the plan. Quota is counted per rolling week rather
    # than granted, so this does not need to replenish anything - it exists so
    # an account that lapsed and then paid again is restored without waiting for
    # a new Checkout, and so a missed event can never silently zero an account.
    if event_type in ("invoice.paid", "invoice.payment_succeeded"):
        installation_id, plan = _subscription_target(data)
        if not installation_id or plan not in PLANS:
            return None
        set_plan(int(installation_id), plan)
        return f"installation {installation_id} renewed on {plan}"

    # A plan change mid-cycle: upgrade, downgrade, or a subscription that has
    # entered a state Stripe no longer considers good standing.
    if event_type == "customer.subscription.updated":
        installation_id, plan = _subscription_target(data)
        if not installation_id:
            return None
        status = data.get("status")
        if status in ("active", "trialing") and plan in PLANS:
            set_plan(int(installation_id), plan)
            return f"installation {installation_id} now on {plan}"
        if status in ("canceled", "unpaid", "incomplete_expired"):
            set_plan(int(installation_id), "unpaid")
            return f"installation {installation_id} returned to unpaid ({status})"
        return None

    if event_type in ("customer.subscription.deleted", "invoice.payment_failed"):
        installation_id, _ = _subscription_target(data)
        if not installation_id:
            return None
        set_plan(int(installation_id), "unpaid")
        return f"installation {installation_id} returned to unpaid"

    return None


def _subscription_target(data: dict) -> tuple[str | None, str | None]:
    """Digs the installation and plan out of a Stripe object.

    Subscription events carry our metadata on the subscription; invoice events
    carry it in `subscription_details`, or on lines when Stripe copied it there.
    Checking each in turn is what stops a renewal being silently ignored because
    it arrived in a shape we didn't look at."""
    candidates = [
        data.get("metadata") or {},
        (data.get("subscription_details") or {}).get("metadata") or {},
    ]
    for line in ((data.get("lines") or {}).get("data") or []):
        candidates.append(line.get("metadata") or {})

    for metadata in candidates:
        installation_id = metadata.get("installation_id")
        if installation_id:
            return installation_id, metadata.get("plan")
    return None, None


def set_plan(installation_id: int, plan: str, db_path: str | None = None) -> None:
    """Records which plan an installation is on. Quota is derived from the plan
    and the reviews actually run, so there is no balance to write here."""
    with store.connect(db_path) as connection:
        connection.execute(
            "UPDATE installations SET plan = ?, updated_at = ? WHERE id = ?",
            (plan, int(time.time()), installation_id),
        )


def billing_status(installation_id: int, db_path: str | None = None) -> dict:
    installation = store.get_installation(installation_id, db_path)
    if installation is None:
        return {"plan": "unknown", "configured": configured()}
    quota = store.quota_status(installation_id, db_path)
    return {
        "plan": installation["plan"],
        "quota": quota,
        "planDetails": plan_details(installation["plan"]),
        "configured": configured(),
    }
