import Link from "next/link";

import { SiteHeader } from "@/components/SiteHeader";
import { Badge, Panel, Section } from "@/components/ui";

/**
 * The landing page.
 *
 * style.md 5-6: the hero shows the product doing something, next to one obvious
 * action. Whoever follows a teammate's link has never heard of this, so it
 * leads with the problem rather than the feature list.
 *
 * Statically rendered - no client JavaScript except the auth nav.
 */

const SAMPLE_FINDINGS = [
  {
    tone: "critical" as const,
    label: "Critical",
    fn: "swap()",
    title: "Storage contention",
    body: "reserve0, reserve1 and totalLiquidity are written on every swap, so concurrent swaps serialise.",
  },
  {
    tone: "warn" as const,
    label: "High",
    fn: "deposit()",
    title: "Repeated storage read",
    body: "balance[user] is loaded four times in one path.",
  },
  {
    tone: "accent" as const,
    label: "Medium",
    fn: "claim()",
    title: "Write with no state change",
    body: "lastClaim is rewritten even when the value is unchanged.",
  },
];

const STAGES = [
  {
    name: "Static",
    body: "Slither's detector suite plus ParaCheck's hot-slot classifier, mapping which functions touch which storage.",
  },
  {
    name: "Dynamic",
    body: "Foundry and anvil run the contract under concurrent load, and the execution traces are diffed for real conflicts.",
  },
  {
    name: "Report",
    body: "Findings are prioritised by measured impact and posted to the pull request as a Check Run with inline annotations.",
  },
];

const STACK = [
  ["Static analysis", "Slither + hot-slot classifier"],
  ["Dynamic analysis", "Foundry / anvil execution traces"],
  ["Proof engine", "Generated Foundry PoCs, validated by execution"],
  ["Control plane", "Cloudflare Workers + D1"],
  ["Execution", "GitHub Actions, on your own runner"],
  ["Integration", "Native PR Check Runs and annotations"],
];

export default function Home() {
  return (
    <>
      <SiteHeader />
      <main id="main" className="wrap">
        <section className="section first">
          <div className="hero">
            <div>
              <h1>Every finding is one you can run.</h1>
              <p className="lede" style={{ marginTop: 20 }}>
                ParaCheck measures the storage and parallelism patterns making your Solidity
                slow on a parallel EVM, and proves the bugs that could drain it &mdash; each
                finding backed by a trace or a failing test you can reproduce. Only proven
                findings block a merge.
              </p>
              <div className="btn-row" style={{ marginTop: 28 }}>
                <Link className="btn" href="/dashboard">
                  Connect GitHub
                </Link>
                <Link className="btn secondary" href="#how">
                  See how it works
                </Link>
              </div>
              <p className="small dim" style={{ marginTop: 16 }}>
                Scans run on every pull request, or on demand from the dashboard.
              </p>
            </div>

            <Panel pad={false} className="proof">
              <div className="proof-head">
                <code className="mono">NaiveAMM.sol</code>
                <Badge>Sample report</Badge>
              </div>
              <div className="proof-summary">
                <div>
                  <div className="stat-label">Optimisation opportunities</div>
                  <div className="stat-value">3</div>
                </div>
                <div>
                  <div className="stat-label">Contended slots</div>
                  <div className="stat-value is-critical">2</div>
                </div>
              </div>
              {SAMPLE_FINDINGS.map((finding) => (
                <div className="finding" key={finding.fn}>
                  <div className="finding-head">
                    <Badge tone={finding.tone}>{finding.label}</Badge>
                    <code className="fn">{finding.fn}</code>
                  </div>
                  <div className="finding-title">{finding.title}</div>
                  <p className="finding-body">{finding.body}</p>
                </div>
              ))}
            </Panel>
          </div>
        </section>

        <Section eyebrow="The problem">
          <div className="grid grid-2" style={{ gap: 56 }}>
            <p className="lede">
              On a chain that executes transactions in parallel, two transactions touching the
              same storage slot cannot run at the same time. One is thrown away and
              re-executed.
            </p>
            <p className="lede">
              That cost is decided when the contract is written, and it is invisible in a
              normal diff. Nothing in a standard review tells you which slots will contend.
            </p>
          </div>
        </Section>

        <Section eyebrow="How ParaCheck finds it" id="how">
          <div className="grid grid-3" style={{ gap: 40 }}>
            {STAGES.map((stage) => (
              <div key={stage.name}>
                <div className="stat-label">{stage.name}</div>
                <p className="muted" style={{ fontSize: 14, marginTop: 8 }}>
                  {stage.body}
                </p>
              </div>
            ))}
          </div>
        </Section>

        <Section eyebrow="In your pull requests">
          <Panel>
            <ul className="rows">
              <li>
                <code className="inline">1</code> Sign in and install the app on the
                repositories you choose.
              </li>
              <li>
                <code className="inline">2</code> Scan a repository straight away, or open a
                pull request that touches a <code className="inline">.sol</code> file.
              </li>
              <li>
                <code className="inline">3</code> The analysis runs on your own GitHub Actions
                runner, authenticated by OIDC. Your source never reaches our servers.
              </li>
              <li>
                <code className="inline">4</code> A Check Run appears with annotations and a
                reproduce command &mdash; and only a proven finding can gate the merge.
              </li>
            </ul>
          </Panel>
        </Section>

        <Section eyebrow="What it is built on">
          <Panel>
            <ul className="rows">
              {STACK.map(([name, detail]) => (
                <li key={name}>
                  {name}
                  <span className="spacer muted">{detail}</span>
                </li>
              ))}
            </ul>
          </Panel>
          <p className="small dim" style={{ marginTop: 14 }}>
            Analysis runs as a GitHub Actions job on your own runner, authenticated back with a
            short-lived OIDC token. There is no secret to store, and the control plane never
            receives a copy of your code.
          </p>
        </Section>

        <section className="section">
          <Panel>
            <div style={{ display: "flex", gap: 24, alignItems: "center", flexWrap: "wrap" }}>
              <div>
                <h3>Put ParaCheck in your pull requests.</h3>
                <p className="muted" style={{ fontSize: 14, marginTop: 6 }}>
                  One install. No configuration file, no YAML, no compiler settings.
                </p>
              </div>
              <div className="btn-row" style={{ marginLeft: "auto" }}>
                <Link className="btn" href="/dashboard">
                  Connect GitHub
                </Link>
                <Link className="btn secondary" href="/pricing">
                  See pricing
                </Link>
              </div>
            </div>
          </Panel>
        </section>
      </main>
    </>
  );
}
