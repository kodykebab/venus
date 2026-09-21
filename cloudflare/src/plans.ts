/**
 * Plans and quota.
 *
 * These numbers are the single source of truth: the pricing page, the
 * dashboard, the checkout and the gate that actually refuses a scan all read
 * them from here, so they cannot drift apart.
 *
 * Quotas are per rolling 30 days rather than per calendar month or per billing
 * period. Counting from the scans actually run means there is no balance to
 * replenish and therefore no reset to miss - a Stripe event that never arrives
 * cannot leave a paying account throttled to zero - and quota frees up
 * continuously instead of everyone's usage spiking on the 1st.
 *
 * Note on what a quota is for here: the analysis runs on the customer's own
 * GitHub Actions runner, so a scan costs us essentially nothing. These limits
 * are a monetisation boundary, not cost control. That is why the free tier can
 * be genuinely useful rather than a crippled demo.
 */

export type PlanKey = "free" | "pro" | "enterprise";

export interface Plan {
  key: PlanKey;
  label: string;
  price: string;
  cadence: string;
  /** Scans per rolling 30 days. null means no fixed cap (enterprise only). */
  scansPerMonth: number | null;
  priceEnv?: "STRIPE_PRO_PRICE_ID";
  blurb: string;
  features: string[];
}

export const PLANS: Record<string, Plan> = {
  free: {
    key: "free",
    label: "Free",
    price: "$0",
    cadence: "",
    scansPerMonth: 10,
    blurb: "Enough to keep a contract honest and see what this finds.",
    features: [
      "10 scans per month",
      "GitHub PR Check Runs and inline annotations",
      "Static analysis: Slither + hot-slot classifier",
      "Dynamic contention analysis",
    ],
  },
  pro: {
    key: "pro",
    label: "Pro",
    price: "$19",
    cadence: "/month",
    scansPerMonth: 50,
    priceEnv: "STRIPE_PRO_PRICE_ID",
    blurb: "For a team shipping to a parallel-execution chain.",
    features: [
      "50 scans per month",
      "Everything in Free",
      "Unlimited repositories per installation",
      "Merge gating on severity thresholds",
    ],
  },
  enterprise: {
    key: "enterprise",
    label: "Enterprise",
    price: "Custom",
    cadence: "",
    scansPerMonth: null,
    blurb: "For protocols with their own volume, deployment and support needs.",
    features: [
      "Custom monthly scan quota",
      "Everything in Pro",
      "Self-hosted or dedicated deployment options",
      "Direct support channel",
    ],
  },
};

/** Plans that can be bought online. Free needs no checkout; Enterprise is sales-led. */
export const PURCHASABLE = ["pro"] as const;

/** The default an account lands on, and the one a cancelled subscription returns to. */
export const DEFAULT_PLAN: PlanKey = "free";

export const QUOTA_WINDOW_SECONDS = 30 * 24 * 3600;

/**
 * Scans permitted per rolling 30 days.
 *
 * `null` is "no fixed cap" and is only ever enterprise. An unrecognised plan
 * falls back to the free allowance rather than zero: the failure mode of a
 * typo should be a customer getting the free tier, not a paying customer
 * locked out. "unpaid" is accepted as a historical alias for free, since
 * cancelling a subscription returns an account to the free tier.
 */
export function scanLimit(plan: string): number | null {
  if (plan === "enterprise") return null;
  const found = PLANS[plan];
  if (found && found.key !== "enterprise") return found.scansPerMonth;
  return PLANS.free.scansPerMonth;
}

export interface Quota {
  plan: string;
  limit: number | null;
  used: number;
  remaining: number | null;
  resetsAt: number | null;
}

export interface QuotaDecision {
  allowed: boolean;
  reason: string;
  quota: Quota;
}

export function decide(quota: Quota): QuotaDecision {
  if (quota.limit === null) {
    return { allowed: true, reason: "", quota };
  }
  if (quota.used >= quota.limit) {
    const when = quota.resetsAt ? ` Quota frees up in ${humanUntil(quota.resetsAt)}.` : "";
    const upgrade =
      quota.plan === "pro" || quota.plan === "enterprise"
        ? ""
        : ` ${PLANS.pro.label} is ${PLANS.pro.price}${PLANS.pro.cadence} for ${PLANS.pro.scansPerMonth}.`;
    return {
      allowed: false,
      reason:
        `This month's quota is used up (${quota.used}/${quota.limit} scans in the last 30 days).` +
        when +
        upgrade,
      quota,
    };
  }
  return { allowed: true, reason: "", quota };
}

export function humanUntil(timestamp: number): string {
  const seconds = Math.max(timestamp - Math.floor(Date.now() / 1000), 0);
  if (seconds < 3600) return `${Math.max(Math.floor(seconds / 60), 1)} minutes`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} hours`;
  return `${Math.floor(seconds / 86400)} days`;
}
