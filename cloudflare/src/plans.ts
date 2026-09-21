/**
 * Plans and quota.
 *
 * These numbers are the single source of truth: the pricing page, the
 * dashboard, the checkout selector and the gate that actually refuses a scan
 * all read them from here, so they cannot drift apart.
 *
 * Quotas are per rolling seven days, not per billing period. A scan compiles
 * and analyses an arbitrary repository, so the cost is CPU and minutes and has
 * to be bounded at the rate it is incurred rather than granted monthly.
 */

export type PlanKey = "hobby" | "pro" | "enterprise" | "unpaid";

export interface Plan {
  key: PlanKey;
  label: string;
  price: string;
  cadence: string;
  /** Scans per rolling week. null means no fixed cap (enterprise only). */
  scansPerWeek: number | null;
  priceEnv?: "STRIPE_HOBBY_PRICE_ID" | "STRIPE_PRO_PRICE_ID";
  blurb: string;
  features: string[];
}

export const PLANS: Record<string, Plan> = {
  hobby: {
    key: "hobby",
    label: "Hobby",
    price: "$9",
    cadence: "/month",
    scansPerWeek: 20,
    priceEnv: "STRIPE_HOBBY_PRICE_ID",
    blurb: "For a developer keeping one or two contracts honest.",
    features: [
      "20 scans per week",
      "GitHub PR Check Runs and inline annotations",
      "Static analysis: Slither + hot-slot classifier",
      "Dynamic contention analysis",
    ],
  },
  pro: {
    key: "pro",
    label: "Pro",
    price: "$29",
    cadence: "/month",
    scansPerWeek: 100,
    priceEnv: "STRIPE_PRO_PRICE_ID",
    blurb: "For a team shipping to a parallel-execution chain.",
    features: [
      "100 scans per week",
      "Everything in Hobby",
      "Unlimited repositories per installation",
      "Merge gating on severity thresholds",
    ],
  },
  enterprise: {
    key: "enterprise",
    label: "Enterprise",
    price: "Custom",
    cadence: "",
    scansPerWeek: null,
    blurb: "For protocols with their own volume, deployment and support needs.",
    features: [
      "Custom weekly scan quota",
      "Everything in Pro",
      "Self-hosted or dedicated deployment options",
      "Direct support channel",
    ],
  },
};

/** Plans that can be bought online. Enterprise is sales-led. */
export const PURCHASABLE = ["hobby", "pro"] as const;

export const QUOTA_WINDOW_SECONDS = 7 * 24 * 3600;

/**
 * Scans permitted per rolling week. `null` is "no fixed cap" and is only ever
 * enterprise; an unpaid or unrecognised plan is 0, never unlimited - a typo in
 * a plan name must fail closed.
 */
export function scansPerWeek(plan: string): number | null {
  if (plan === "enterprise") return null;
  const found = PLANS[plan];
  return found && found.key !== "enterprise" ? found.scansPerWeek : 0;
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
  if (quota.limit === 0) {
    // Unpaid, lapsed, or an unknown plan. Say what to do rather than reporting
    // a quota of zero, which reads like a bug rather than a paywall.
    return {
      allowed: false,
      reason: "Choose a Hobby or Pro plan to start scanning.",
      quota,
    };
  }
  if (quota.used >= quota.limit) {
    const when = quota.resetsAt ? ` Quota frees up in ${humanUntil(quota.resetsAt)}.` : "";
    return {
      allowed: false,
      reason: `This week's quota is used up (${quota.used}/${quota.limit} scans in the last 7 days).${when}`,
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
