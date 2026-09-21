import type { Metadata } from "next";

import { SiteHeader } from "@/components/SiteHeader";
import { PlanGrid } from "@/components/PlanGrid";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "ParaCheck pricing: Hobby $9/month for 20 scans a week, Pro $29/month for 100, Enterprise custom.",
};

/**
 * style.md 34: simple, quotas stated plainly, no fake discounts or countdowns.
 *
 * The page is static; only the buttons need a session, and those live in the
 * client component so the rest ships as HTML.
 */
export default function PricingPage() {
  return (
    <>
      <SiteHeader />
      <main id="main" className="wrap">
        <section className="section first">
          <h1 style={{ fontSize: "clamp(32px,4.4vw,52px)" }}>Pricing</h1>
          <p className="lede" style={{ marginTop: 16 }}>
            A scan compiles and analyses a repository, so plans are capped by scans per week
            rather than sold as unlimited. Quota is counted over a rolling seven days, so it
            frees up continuously instead of resetting on one day of the month.
          </p>
        </section>

        <section className="section" style={{ marginTop: 48 }}>
          <PlanGrid />
          <p className="small dim" style={{ marginTop: 20 }}>
            A scan is one analysis of one pull request or one branch. Pushing again to an
            open pull request replaces the queued scan rather than spending another one.
          </p>
        </section>
      </main>
    </>
  );
}
