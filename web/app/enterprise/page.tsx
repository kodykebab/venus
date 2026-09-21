import type { Metadata } from "next";
import Link from "next/link";

import { SiteHeader } from "@/components/SiteHeader";
import { Panel, Section } from "@/components/ui";
import { enterpriseMailto, PLANS, SALES_EMAIL } from "@/lib/plans";

export const metadata: Metadata = {
  title: "Enterprise",
  description:
    "Custom weekly scan quota, dedicated deployment options and a direct support channel.",
};

/** Sales-led, so this page's only job is to open a prefilled message. */
export default function EnterprisePage() {
  const enterprise = PLANS.find((plan) => plan.key === "enterprise");

  return (
    <>
      <SiteHeader />
      <main id="main" className="wrap">
        <section className="section first">
          <h1 style={{ fontSize: "clamp(32px,4.4vw,52px)", maxWidth: "16ch" }}>
            Let&rsquo;s talk.
          </h1>
          <p className="lede" style={{ marginTop: 16 }}>
            Tell us the repositories you want covered, the chains you ship to and roughly how
            many pull requests a week. We&rsquo;ll design a capped plan around it and send a
            quote.
          </p>
          <div className="btn-row" style={{ marginTop: 28 }}>
            <a className="btn" href={enterpriseMailto()}>
              Email us
            </a>
            <Link className="btn secondary" href="/pricing">
              Compare plans
            </Link>
          </div>
          <p className="small dim" style={{ marginTop: 14 }}>
            Opens your mail client with the details we need already filled in. Goes to{" "}
            <code className="inline">{SALES_EMAIL}</code>.
          </p>
        </section>

        <Section eyebrow="What Enterprise includes">
          <Panel>
            <ul className="rows">
              {(enterprise?.features ?? []).map((feature) => (
                <li key={feature}>{feature}</li>
              ))}
            </ul>
          </Panel>
        </Section>
      </main>
    </>
  );
}
