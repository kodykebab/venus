/**
 * The shared primitives every page is built from.
 *
 * style.md 51.1-51.3: build the visual system before the pages, and reuse the
 * product's own components on the marketing site so the marketing site is a
 * preview of the real thing rather than a separate design.
 */
import type { ReactNode } from "react";

export type Tone = "ok" | "warn" | "critical" | "accent" | "";

export function Section({
  eyebrow,
  children,
  first = false,
  id,
}: {
  eyebrow: string;
  children: ReactNode;
  first?: boolean;
  id?: string;
}) {
  return (
    <section className={first ? "section first" : "section"} id={id}>
      <h2 className="eyebrow">{eyebrow}</h2>
      {children}
    </section>
  );
}

export function Panel({
  children,
  pad = true,
  className = "",
}: {
  children: ReactNode;
  pad?: boolean;
  className?: string;
}) {
  return (
    <div className={`panel${pad ? " panel-pad" : ""}${className ? ` ${className}` : ""}`}>
      {children}
    </div>
  );
}

/**
 * Status always carries a dot, a word and a colour - never colour on its own,
 * which is invisible to anyone who cannot distinguish it (style.md 45).
 */
export function Badge({ children, tone = "" }: { children: ReactNode; tone?: Tone }) {
  return (
    <span className={`badge${tone ? ` is-${tone}` : ""}`}>
      <span className="dot" aria-hidden="true" />
      {children}
    </span>
  );
}

export function Stat({
  label,
  value,
  note,
  tone = "",
}: {
  label: string;
  value: ReactNode;
  note?: string;
  tone?: Tone;
}) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value${tone ? ` is-${tone}` : ""}`}>{value}</div>
      {note ? <div className="stat-note">{note}</div> : null}
    </div>
  );
}

/**
 * style.md 28: never "nothing here yet". Say what the surface is, why it is
 * empty, and what to do next.
 */
export function EmptyState({
  heading,
  body,
  action,
}: {
  heading: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="panel">
      <div className="state">
        <h3>{heading}</h3>
        <p>{body}</p>
        {action ? <div className="btn-row">{action}</div> : null}
      </div>
    </div>
  );
}

export function Notice({
  tone = "ok",
  children,
}: {
  tone?: "ok" | "error" | "warn";
  children: ReactNode;
}) {
  return (
    <div className={`notice is-${tone}`} role="status">
      {children}
    </div>
  );
}

/** "3h ago" answers "is this thing running?"; a timestamp makes you subtract. */
export function ago(seconds: number | null | undefined): string {
  if (!seconds) return "-";
  let delta = Math.max(Math.floor(Date.now() / 1000) - seconds, 0);
  for (const [size, unit] of [
    [60, "s"],
    [60, "m"],
    [24, "h"],
    [365, "d"],
  ] as const) {
    if (delta < size) return `${delta}${unit} ago`;
    delta = Math.floor(delta / size);
  }
  return `${delta}y ago`;
}

export function until(seconds: number | null | undefined): string {
  if (!seconds) return "-";
  const delta = Math.max(seconds - Math.floor(Date.now() / 1000), 0);
  if (delta < 3600) return `${Math.max(Math.floor(delta / 60), 1)}m`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h`;
  return `${Math.floor(delta / 86400)}d`;
}
