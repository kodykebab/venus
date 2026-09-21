import { hmacSha256Hex, timingSafeEqual } from "./crypto";
import * as db from "./db";
import type { Env } from "./env";
import { DEFAULT_PLAN, PLANS, PURCHASABLE } from "./plans";

/**
 * Stripe Checkout and the subscription lifecycle.
 *
 * Direct REST rather than the Stripe SDK: the SDK is a large Node-shaped
 * dependency and this uses four endpoints. Form encoding is Stripe's wire
 * format, not a stylistic choice.
 */

const API = "https://api.stripe.com/v1";
const SIGNATURE_TOLERANCE_SECONDS = 300;

export function configured(env: Env): boolean {
  // Every purchasable plan needs its own Stripe Price. Checking all of them
  // means a half-configured deployment says so on /api/health rather than
  // failing at the moment someone clicks the tier you forgot.
  return Boolean(
    env.STRIPE_SECRET_KEY &&
      PURCHASABLE.every((key) => {
        const priceEnv = PLANS[key].priceEnv;
        return priceEnv ? env[priceEnv] : false;
      }),
  );
}

function priceFor(env: Env, plan: string): string | null {
  const details = PLANS[plan];
  if (!details?.priceEnv) return null;
  return env[details.priceEnv] || null;
}

export async function createCheckoutSession(
  env: Env,
  options: {
    accountId: string;
    plan: string;
    email: string | null;
    successUrl: string;
    cancelUrl: string;
  },
): Promise<string | null> {
  const price = priceFor(env, options.plan);
  if (!price || !env.STRIPE_SECRET_KEY) return null;

  const form = new URLSearchParams({
    mode: "subscription",
    "line_items[0][price]": price,
    "line_items[0][quantity]": "1",
    // The account id rides along in three places because each is read by a
    // different event later: the session, the subscription, and via the
    // customer. Losing it means a completed payment we cannot attribute.
    client_reference_id: options.accountId,
    "metadata[account_id]": options.accountId,
    "metadata[plan]": options.plan,
    "subscription_data[metadata][account_id]": options.accountId,
    "subscription_data[metadata][plan]": options.plan,
    success_url: options.successUrl,
    cancel_url: options.cancelUrl,
    allow_promotion_codes: "true",
  });
  if (options.email) form.set("customer_email", options.email);

  const response = await fetch(`${API}/checkout/sessions`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.STRIPE_SECRET_KEY}`,
      "content-type": "application/x-www-form-urlencoded",
    },
    body: form,
  });
  if (!response.ok) {
    console.error(`paracheck: stripe checkout failed ${response.status}: ${(await response.text()).slice(0, 200)}`);
    return null;
  }
  return ((await response.json()) as { url: string }).url;
}

/** A Stripe-hosted page for changing card, plan or cancelling. */
export async function createPortalSession(
  env: Env,
  customerId: string,
  returnUrl: string,
): Promise<string | null> {
  const response = await fetch(`${API}/billing_portal/sessions`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.STRIPE_SECRET_KEY}`,
      "content-type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({ customer: customerId, return_url: returnUrl }),
  });
  if (!response.ok) return null;
  return ((await response.json()) as { url: string }).url;
}

/**
 * Stripe's scheme: `t=<timestamp>,v1=<hmac>` over "timestamp.payload".
 *
 * The timestamp check is what stops a captured webhook being replayed later to
 * re-activate a cancelled subscription.
 */
export async function verifyWebhook(
  env: Env,
  body: string,
  signatureHeader: string | null,
  nowSeconds = Math.floor(Date.now() / 1000),
): Promise<boolean> {
  if (!env.STRIPE_WEBHOOK_SECRET || !signatureHeader) return false;

  const parts = new Map(
    signatureHeader
      .split(",")
      .map((piece) => piece.split("=", 2))
      .filter((pair): pair is [string, string] => pair.length === 2),
  );
  const timestamp = parts.get("t");
  const provided = parts.get("v1");
  if (!timestamp || !provided) return false;

  const age = nowSeconds - Number(timestamp);
  if (!Number.isFinite(age) || Math.abs(age) > SIGNATURE_TOLERANCE_SECONDS) return false;

  const expected = await hmacSha256Hex(env.STRIPE_WEBHOOK_SECRET, `${timestamp}.${body}`);
  return timingSafeEqual(provided, expected);
}

interface StripeObject {
  id?: string;
  status?: string;
  customer?: string;
  subscription?: string;
  client_reference_id?: string;
  metadata?: Record<string, string>;
  subscription_details?: { metadata?: Record<string, string> };
  lines?: { data?: Array<{ metadata?: Record<string, string> }> };
}

/**
 * Digs the account and plan out of a Stripe object.
 *
 * Subscription events carry our metadata on the subscription; invoice events
 * carry it under `subscription_details`, or on the line items when Stripe
 * copied it there. Checking each in turn is what stops a renewal being
 * silently ignored because it arrived in a shape we did not look at.
 */
function target(object: StripeObject): { accountId: string | null; plan: string | null } {
  const candidates: Array<Record<string, string> | undefined> = [
    object.metadata,
    object.subscription_details?.metadata,
    ...(object.lines?.data ?? []).map((line) => line.metadata),
  ];
  for (const metadata of candidates) {
    if (metadata?.account_id) {
      return { accountId: metadata.account_id, plan: metadata.plan ?? null };
    }
  }
  return { accountId: object.client_reference_id ?? null, plan: null };
}

/**
 * Applies a verified event. Returns a short description of what changed, or
 * null when the event is not one we act on.
 */
export async function applyEvent(
  env: Env,
  event: { type: string; data: { object: StripeObject } },
): Promise<string | null> {
  const object = event.data.object;
  const { accountId, plan } = target(object);

  switch (event.type) {
    case "checkout.session.completed": {
      if (!accountId || !plan || !PURCHASABLE.includes(plan as never)) return null;
      await db.setPlan(env.DB, accountId, plan, {
        customerId: object.customer,
        subscriptionId: object.subscription,
      });
      return `${accountId} subscribed to ${plan}`;
    }

    // A renewal re-asserts the plan. Quota is counted per rolling 30 days rather
    // than granted, so nothing needs replenishing here - this exists so an
    // account that lapsed and paid again is restored without a new Checkout.
    case "invoice.paid":
    case "invoice.payment_succeeded": {
      if (!accountId || !plan || !PURCHASABLE.includes(plan as never)) return null;
      await db.setPlan(env.DB, accountId, plan, { customerId: object.customer });
      return `${accountId} renewed on ${plan}`;
    }

    case "customer.subscription.updated": {
      if (!accountId) return null;
      if ((object.status === "active" || object.status === "trialing") && plan) {
        await db.setPlan(env.DB, accountId, plan);
        return `${accountId} now on ${plan}`;
      }
      if (["canceled", "unpaid", "incomplete_expired"].includes(object.status ?? "")) {
        await db.setPlan(env.DB, accountId, DEFAULT_PLAN);
        return `${accountId} returned to the free tier (${object.status})`;
      }
      return null;
    }

    case "customer.subscription.deleted":
    case "invoice.payment_failed": {
      if (!accountId) return null;
      await db.setPlan(env.DB, accountId, DEFAULT_PLAN);
      return `${accountId} returned to the free tier`;
    }

    default:
      return null;
  }
}
