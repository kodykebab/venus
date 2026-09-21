"use client";

import Link from "next/link";
import { Fragment, useCallback, useEffect, useState } from "react";

import { api, ApiError, type Me, type Quota, type Scan, type ScanDetail } from "@/lib/api";
import { PLANS } from "@/lib/plans";
import { ago, Badge, EmptyState, Notice, Panel, Section, Stat, until, type Tone } from "./ui";
import { AnthropicKeyPanel } from "./AnthropicKeyPanel";
import { FindingList } from "./FindingList";
import { ScanActivity } from "./ScanActivity";

/**
 * The dashboard.
 *
 * style.md 30 and 48: it answers "how are my contracts doing?", and each
 * surface has exactly one dominant action - here, scanning a repository. The
 * upgrade prompt only appears once the free allowance is nearly gone, because
 * a paywall on day one would undo the point of having a free tier.
 */

const SCAN_STATE: Record<string, { label: string; tone: Tone }> = {
  queued: { label: "Queued", tone: "accent" },
  running: { label: "Scanning", tone: "accent" },
  done: { label: "Scanned", tone: "ok" },
  empty: { label: "No Solidity", tone: "" },
  failed: { label: "Failed", tone: "critical" },
  blocked: { label: "Not run", tone: "warn" },
  no_workflow: { label: "Needs setup", tone: "warn" },
};

export function Dashboard() {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [scanning, setScanning] = useState<string | null>(null);
  const [settingUp, setSettingUp] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setMe(await api<Me>("/api/me"));
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load your account.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // While anything is in flight, poll: a scan finishing is the whole point of
  // the page, and making someone refresh to see it would be a poor tell.
  const inFlight = me?.scans.some((s) => s.state === "queued" || s.state === "running") ?? false;
  useEffect(() => {
    if (!inFlight) return;
    const timer = setInterval(() => void load(), 5000);
    return () => clearInterval(timer);
  }, [inFlight, load]);

  async function scan(installationId: number, repository: string) {
    setScanning(repository);
    setNotice(null);
    setError(null);
    try {
      await api("/api/scans", { method: "POST", body: { installationId, repository } });
      // No notice here: the repository row's own status badge starts
      // reflecting "Scanning" within the next poll, which said the same
      // thing this banner used to - just already on screen, not on top of it.
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not start that scan.");
    } finally {
      setScanning(null);
      // Reload even on failure: a repository with no workflow file is
      // recorded as a scan row, and the row is what turns the button into
      // "Add workflow" - without this reload that only happens on a manual
      // page refresh.
      await load();
    }
  }

  async function connectGithub() {
    const { url } = await api<{ url: string }>("/api/install?format=json");
    window.location.href = url;
  }

  async function addWorkflow(installationId: number, repository: string) {
    setSettingUp(repository);
    setNotice(null);
    setError(null);
    try {
      const { prUrl } = await api<{ prUrl: string }>("/api/repos/add-workflow", {
        method: "POST",
        body: { installationId, repository },
      });
      // Opened in a new tab rather than navigated to: the dashboard is where
      // the next action (Scan now, once it's merged) still needs to happen.
      window.open(prUrl, "_blank", "noopener,noreferrer");
      setNotice(
        "Opened a pull request adding the workflow file. Nothing runs until you merge it " +
          "- once you do, Scan now and pull-request scans both start working for this repository.",
      );
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not set up that repository.");
    } finally {
      setSettingUp(null);
    }
  }

  if (error && !me) {
    return (
      <Section eyebrow="Dashboard" first>
        <EmptyState
          heading="Could not load your account"
          body={error}
          action={
            <button className="btn" type="button" onClick={() => void load()}>
              Try again
            </button>
          }
        />
      </Section>
    );
  }

  if (!me) {
    return (
      <Section eyebrow="Dashboard" first>
        <Panel>
          <p className="muted">Loading your account&hellip;</p>
        </Panel>
      </Section>
    );
  }

  const canScan = me.quota.limit === null || (me.quota.remaining ?? 0) > 0;
  // Nudge toward Pro only when the free allowance is nearly gone - an upgrade
  // banner on day one is noise, and the free tier is meant to be usable.
  const onFree = !["pro", "team", "enterprise"].includes(me.account.plan);
  const runningLow = onFree && (me.quota.remaining ?? 0) <= 3;

  return (
    <>
      {notice ? (
        <div style={{ marginBottom: 20 }}>
          <Notice tone="ok">{notice}</Notice>
        </div>
      ) : null}
      {error ? (
        <div style={{ marginBottom: 20 }}>
          <Notice tone="error">{error}</Notice>
        </div>
      ) : null}

      <Header me={me} />
      <ScanActivity scans={me.scans} />
      <Summary me={me} />
      {runningLow ? <PlanGate remaining={me.quota.remaining ?? 0} /> : null}
      <Repositories
        me={me}
        canScan={canScan}
        scanning={scanning}
        settingUp={settingUp}
        onScan={scan}
        onAddWorkflow={addWorkflow}
        onConnect={connectGithub}
      />
      <History scans={me.scans} />
      <AnthropicKeyPanel hint={me.account.anthropicKeyHint} onChange={load} />
    </>
  );
}

function Header({ me }: { me: Me }) {
  const plan = PLANS.find((p) => p.key === me.account.plan);
  const { remaining, limit } = me.quota;

  let status = <Badge>Free</Badge>;
  if (plan && limit === null) {
    status = <Badge tone="ok">{plan.label} plan</Badge>;
  } else if (plan) {
    const tone: Tone = (remaining ?? 0) > 3 ? "ok" : (remaining ?? 0) > 0 ? "warn" : "critical";
    status = (
      <Badge tone={tone}>
        {plan.label} &middot; {remaining} of {limit} scans left
      </Badge>
    );
  }

  return (
    <section className="section first">
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <h1 style={{ fontSize: "clamp(26px,3.4vw,36px)" }}>
          {me.installations[0]?.account_login ?? "Your account"}
        </h1>
        {status}
      </div>
      <p className="small dim" style={{ marginTop: 10 }}>
        {me.account.email ?? me.account.id} &middot; {me.installations.length} installation
        {me.installations.length === 1 ? "" : "s"}
      </p>
    </section>
  );
}

function Summary({ me }: { me: Me }) {
  const { quota, scans } = me;
  const repositories = Object.values(me.repositories).reduce((n, list) => n + list.length, 0);
  const findings = scans.reduce((n, scan) => n + scan.findings, 0);
  const waiting = scans.filter((s) => s.state === "queued" || s.state === "running").length;

  const quotaValue =
    quota.limit === null ? quota.used : `${quota.used}/${quota.limit}`;
  const quotaNote =
    quota.limit === null
      ? "this month · no fixed cap"
      : quota.remaining === 0 && quota.resetsAt
        ? `quota frees up in ${until(quota.resetsAt)}`
        : "used in the last 30 days";

  return (
    <Section eyebrow="At a glance">
      <div className="grid grid-4">
        <Stat label="Repositories" value={repositories} note="connected to ParaCheck" />
        <Stat
          label="Scans this month"
          value={quotaValue}
          note={quotaNote}
          tone={quota.limit !== null && quota.remaining === 0 ? "critical" : ""}
        />
        <Stat
          label="Opportunities found"
          value={findings}
          note={scans.length ? `across ${scans.length} scans` : "nothing analysed yet"}
          tone={findings ? "accent" : ""}
        />
        <Stat
          label="In progress"
          value={waiting}
          note={waiting ? "running now" : "idle"}
          tone={waiting ? "accent" : ""}
        />
      </div>
    </Section>
  );
}

function PlanGate({ remaining }: { remaining: number }) {
  // The next step up from free, not the biggest plan on the page.
  const pro = PLANS.find((plan) => plan.key === "pro");
  return (
    <Section eyebrow={remaining === 0 ? "Out of scans" : "Running low"}>
      <Panel>
        <div style={{ display: "flex", gap: 24, alignItems: "center", flexWrap: "wrap" }}>
          <div>
            <h3>
              {remaining === 0
                ? "You've used this month's free scans."
                : `${remaining} free scan${remaining === 1 ? "" : "s"} left this month.`}
            </h3>
            <p className="muted" style={{ fontSize: 14, marginTop: 6, maxWidth: "56ch" }}>
              {pro?.label} is {pro?.price}
              {pro?.cadence} for {pro?.scansPerMonth} scans a month. Quota is counted over a
              rolling 30 days, so it frees up continuously rather than on one day.
            </p>
          </div>
          <div className="btn-row" style={{ marginLeft: "auto" }}>
            <Link className="btn" href="/pricing/">
              Upgrade to {pro?.label}
            </Link>
          </div>
        </div>
      </Panel>
    </Section>
  );
}

function Repositories({
  me,
  canScan,
  scanning,
  settingUp,
  onScan,
  onAddWorkflow,
  onConnect,
}: {
  me: Me;
  canScan: boolean;
  scanning: string | null;
  settingUp: string | null;
  onScan: (installationId: number, repository: string) => void;
  onAddWorkflow: (installationId: number, repository: string) => void;
  onConnect: () => void;
}) {
  const rows = me.installations.flatMap((installation) =>
    (me.repositories[installation.id] ?? []).map((repository) => ({ installation, repository })),
  );

  if (!rows.length) {
    return (
      <Section eyebrow="Repositories">
        <EmptyState
          heading="No repositories connected"
          body="Install ParaCheck on a repository and you can scan it straight away - no pull request needed."
          action={
            <button className="btn" type="button" onClick={onConnect}>
              Connect GitHub
            </button>
          }
        />
      </Section>
    );
  }

  const latest = new Map<string, Scan>();
  for (const scan of me.scans) {
    if (!latest.has(scan.repository)) latest.set(scan.repository, scan);
  }

  return (
    <Section eyebrow="Repositories">
      <Panel pad={false}>
        <table className="responsive">
          <tbody>
            {rows.map(({ installation, repository }) => {
              const scan = latest.get(repository);
              const state = scan ? SCAN_STATE[scan.state] : undefined;
              const needsWorkflow = scan?.state === "no_workflow";
              const busy =
                scanning === repository || settingUp === repository ||
                scan?.state === "queued" || scan?.state === "running";

              return (
                <tr key={repository}>
                  <td data-label="Repository">
                    <code>{repository}</code>
                  </td>
                  <td data-label="Status">
                    {state ? (
                      <>
                        <Badge tone={state.tone}>{state.label}</Badge>{" "}
                        <span className="small dim">
                          {needsWorkflow
                            ? "No paracheck.yml on the default branch yet."
                            : scan?.message ?? ""}
                        </span>
                      </>
                    ) : (
                      <span className="small dim">not scanned yet</span>
                    )}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {busy ? (
                      <span className="small dim">
                        {settingUp === repository ? "opening a pull request\u2026" : "in progress"}
                      </span>
                    ) : needsWorkflow ? (
                      <button
                        className="btn secondary small"
                        type="button"
                        onClick={() => onAddWorkflow(installation.id, repository)}
                      >
                        Add workflow
                      </button>
                    ) : canScan ? (
                      <button
                        className="btn secondary small"
                        type="button"
                        onClick={() => onScan(installation.id, repository)}
                      >
                        Scan now
                      </button>
                    ) : (
                      <span className="small dim">No scans left</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>
      <p className="small dim" style={{ marginTop: 12 }}>
        A scan analyses the default branch and posts the result as a check on that commit.
        Pull requests are scanned automatically.
      </p>
    </Section>
  );
}

function ScanFindings({ entry }: { entry: ScanDetail | "loading" | "error" | undefined }) {
  if (!entry || entry === "loading") {
    return <p className="muted small" style={{ margin: 0 }}>Loading findings&hellip;</p>;
  }
  if (entry === "error") {
    return <p className="muted small" style={{ margin: 0 }}>Could not load this scan's findings.</p>;
  }
  return <FindingList findings={entry.findings} />;
}

function History({ scans }: { scans: Scan[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, ScanDetail | "loading" | "error">>({});

  if (!scans.length) {
    return (
      <Section eyebrow="Scan history">
        <EmptyState
          heading="No scans yet"
          body="The first scan - from a pull request or the Scan now button - will appear here, with what it found."
        />
      </Section>
    );
  }

  async function toggle(scan: Scan) {
    if (scan.state !== "done") return;
    if (expanded === scan.id) {
      setExpanded(null);
      return;
    }
    setExpanded(scan.id);
    if (detail[scan.id] && detail[scan.id] !== "error") return;
    setDetail((prev) => ({ ...prev, [scan.id]: "loading" }));
    try {
      const result = await api<ScanDetail>(`/api/scans/${scan.id}`);
      setDetail((prev) => ({ ...prev, [scan.id]: result }));
    } catch {
      setDetail((prev) => ({ ...prev, [scan.id]: "error" }));
    }
  }

  return (
    <Section eyebrow="Scan history">
      <Panel pad={false}>
        <table className="responsive">
          <thead>
            <tr>
              <th>Repository</th>
              <th>Scan of</th>
              <th>Result</th>
              <th>State</th>
              <th style={{ textAlign: "right" }}>When</th>
            </tr>
          </thead>
          <tbody>
            {scans.map((scan) => {
              const state = SCAN_STATE[scan.state] ?? { label: scan.state, tone: "" as Tone };
              const clickable = scan.state === "done";
              const isOpen = expanded === scan.id;
              return (
                <Fragment key={scan.id}>
                  <tr
                    onClick={() => toggle(scan)}
                    style={clickable ? { cursor: "pointer" } : undefined}
                    aria-expanded={clickable ? isOpen : undefined}
                  >
                    <td data-label="Repository">
                      <code>{scan.repository}</code>
                    </td>
                    <td data-label="Scan of">
                      {scan.pull_request ? (
                        <a
                          href={`https://github.com/${scan.repository}/pull/${scan.pull_request}`}
                          onClick={(e) => e.stopPropagation()}
                        >
                          #{scan.pull_request}
                        </a>
                      ) : scan.head_sha ? (
                        <a
                          href={`https://github.com/${scan.repository}/commit/${scan.head_sha}`}
                          onClick={(e) => e.stopPropagation()}
                        >
                          default branch
                        </a>
                      ) : (
                        <span className="dim">default branch</span>
                      )}
                    </td>
                    <td data-label="Result">
                      {scan.state === "done" ? (
                        scan.findings === 0 ? (
                          <Badge tone="ok">Clean</Badge>
                        ) : (
                          <span className="btn-row" style={{ gap: 6 }}>
                            <Badge tone="warn">{scan.findings} found</Badge>
                            <span className="small" style={{ color: "var(--accent)" }}>
                              {isOpen ? "Hide" : "View"}
                            </span>
                          </span>
                        )
                      ) : (
                        <span className="dim small">&mdash;</span>
                      )}
                    </td>
                    <td data-label="State">
                      <Badge tone={state.tone}>{state.label}</Badge>
                    </td>
                    <td data-label="When" className="small dim" style={{ textAlign: "right" }}>
                      {ago(scan.created_at)}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr>
                      <td colSpan={5} style={{ background: "var(--surface-2)", padding: "18px 16px" }}>
                        <ScanFindings entry={detail[scan.id]} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </Panel>
    </Section>
  );
}
