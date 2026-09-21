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
  key: "free" | "pro" | "team" | "enterprise";
  label: string;
  price: string;
  cadence: string;
  scansPerMonth: number | null;
  blurb: string;
  features: string[];
}

export const PLANS: Plan[] = [
  {
    key: "free",
    label: "Free",
    price: "$0",
    cadence: "",
    scansPerMonth: 10,
    blurb: "Enough to keep a contract honest and see what this finds.",
    // Everything ParaCheck does is on every tier, and the list says so rather
    // than inventing paid-only capabilities. The analysis runs from a workflow
    // file the customer owns, so merge gating and repository count are not
    // things we could withhold even if we wanted to.
    features: [
      "10 scans per month",
      "GitHub PR Check Runs and inline annotations",
      "Static analysis: Slither + hot-slot classifier",
      "Dynamic contention analysis",
      "Merge gating on severity thresholds",
      "Bring your own Claude key",
    ],
  },
  {
    key: "pro",
    label: "Pro",
    price: "$24",
    cadence: "/month",
    scansPerMonth: 100,
    blurb: "For one developer shipping regularly.",
    features: ["100 scans per month", "Everything in Free"],
  },
  {
    key: "team",
    label: "Team",
    price: "$49",
    cadence: "/month",
    scansPerMonth: 250,
    blurb: "For a team shipping to a parallel-execution chain.",
    features: ["250 scans per month", "Everything in Pro"],
  },
  {
    key: "enterprise",
    label: "Enterprise",
    price: "Custom",
    cadence: "",
    scansPerMonth: null,
    blurb: "For protocols with their own volume, deployment and support needs.",
    features: [
      "Custom monthly scan quota",
      "Everything in Team",
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
