/**
 * Plans, mirrored from the Worker's `src/plans.ts`.
 *
 * Duplicated deliberately: the marketing pages are statically exported, so they
 * cannot fetch this at build time from a Worker that may not be deployed yet.
 * The duplication is guarded - `npm run check:plans` at the repo root diffs
 * these numbers against the Worker's, and the Worker is the one that actually
 * enforces them. If they ever disagree, the check fails rather than a customer
 * discovering it.
 */

export interface Plan {
  key: "hobby" | "pro" | "enterprise";
  label: string;
  price: string;
  cadence: string;
  scansPerWeek: number | null;
  blurb: string;
  features: string[];
}

export const PLANS: Plan[] = [
  {
    key: "hobby",
    label: "Hobby",
    price: "$9",
    cadence: "/month",
    scansPerWeek: 20,
    blurb: "For a developer keeping one or two contracts honest.",
    features: [
      "20 scans per week",
      "GitHub PR Check Runs and inline annotations",
      "Static analysis: Slither + hot-slot classifier",
      "Dynamic contention analysis",
    ],
  },
  {
    key: "pro",
    label: "Pro",
    price: "$29",
    cadence: "/month",
    scansPerWeek: 100,
    blurb: "For a team shipping to a parallel-execution chain.",
    features: [
      "100 scans per week",
      "Everything in Hobby",
      "Unlimited repositories per installation",
      "Merge gating on severity thresholds",
    ],
  },
  {
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
];

export const SALES_EMAIL = process.env.NEXT_PUBLIC_SALES_EMAIL ?? "sales@paracheck.dev";

/**
 * A prefilled enquiry, because "email us" with an empty compose window is where
 * most enterprise enquiries quietly die.
 */
export function enterpriseMailto(email: string = SALES_EMAIL): string {
  const subject = "ParaCheck Enterprise enquiry";
  const body = [
    "Hi ParaCheck team,",
    "",
    "We're looking at ParaCheck for our contracts.",
    "",
    "Company:",
    "Repositories to cover:",
    "Chains we ship to:",
    "Approximate pull requests per week:",
    "What we need (quota, deployment, support):",
    "",
    "Thanks,",
    "",
  ].join("\n");
  return `mailto:${email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}
