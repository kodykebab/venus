"use client";

import { useState } from "react";

import type { Scan } from "@/lib/api";
import { Badge, ago, type Tone } from "./ui";

/**
 * Recent scans, at a glance - replaces the "Scanning..." notice that used to
 * sit here. That notice only ever restated what the row's own status badge
 * already showed; this shows something the badges don't: activity and
 * outcome across recent history in one shape, real data only.
 *
 * Bar height is the finding count, bar color is the outcome - never color
 * alone (style.md 45 / ui.tsx's Badge), so the legend and per-bar tooltip
 * both carry the status as text too.
 */

type Status = "clean" | "found" | "failed" | "running" | "other";

const STATUS: Record<Status, { label: string; tone: Tone }> = {
  clean: { label: "Clean", tone: "ok" },
  found: { label: "Findings", tone: "warn" },
  failed: { label: "Failed", tone: "critical" },
  running: { label: "In progress", tone: "accent" },
  other: { label: "Not run", tone: "" },
};

// Fixed order, not the order statuses happen to first appear in - a legend
// that reorders itself as data changes is harder to scan run over run.
const STATUS_ORDER: Status[] = ["clean", "found", "failed", "running", "other"];

function statusOf(scan: Scan): Status {
  if (scan.state === "queued" || scan.state === "running") return "running";
  if (scan.state === "failed") return "failed";
  if (scan.state === "done") return scan.findings > 0 ? "found" : "clean";
  return "other"; // blocked, no_workflow, empty
}

export function ScanActivity({ scans }: { scans: Scan[] }) {
  const [hovered, setHovered] = useState<number | null>(null);

  if (!scans.length) return null;

  // Newest-first from the API; oldest-to-newest reads left-to-right like a
  // timeline, with "now" on the right where the eye lands last.
  const bars = scans.slice(0, 25).slice().reverse();
  const maxFindings = Math.max(1, ...bars.map((s) => s.findings));
  const present = STATUS_ORDER.filter((s) => bars.some((scan) => statusOf(scan) === s));

  return (
    <div className="activity">
      <div className="activity-bars">
        {bars.map((scan, i) => {
          const status = statusOf(scan);
          const heightPct = scan.findings > 0 ? Math.max(12, (scan.findings / maxFindings) * 100) : 8;
          return (
            <button
              key={scan.id}
              type="button"
              className="activity-bar-hit"
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered((h) => (h === i ? null : h))}
              onFocus={() => setHovered(i)}
              onBlur={() => setHovered((h) => (h === i ? null : h))}
            >
              <span
                className={`activity-bar is-${STATUS[status].tone || "none"}`}
                style={{ height: `${heightPct}%` }}
              />
              {hovered === i ? (
                <span className="activity-tip" role="tooltip">
                  <strong>{scan.findings}</strong> {scan.findings === 1 ? "finding" : "findings"}
                  <br />
                  <span className="activity-tip-sub">
                    {scan.repository.split("/")[1] ?? scan.repository}
                  </span>
                  <br />
                  <span className="activity-tip-sub">
                    {STATUS[status].label} &middot; {ago(scan.created_at)}
                  </span>
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
      <div className="activity-legend">
        {present.map((status) => (
          <Badge key={status} tone={STATUS[status].tone}>
            {STATUS[status].label}
          </Badge>
        ))}
      </div>
      <style>{`
        .activity { padding: 16px 0 4px; }
        .activity-bars {
          display: flex; align-items: flex-end; gap: 2px; height: 56px;
        }
        .activity-bar-hit {
          flex: 1 1 0; min-width: 3px; max-width: 20px; height: 100%;
          display: flex; align-items: flex-end; justify-content: center;
          padding: 0; margin: 0; border: none; background: transparent;
          cursor: pointer; position: relative;
        }
        .activity-bar {
          width: 100%; min-height: 4px; border-radius: 4px 4px 0 0;
          background: var(--ink-3);
        }
        .activity-bar.is-ok { background: var(--ok); }
        .activity-bar.is-warn { background: var(--warn); }
        .activity-bar.is-critical { background: var(--critical); }
        .activity-bar.is-accent { background: var(--accent); }
        .activity-bar-hit:hover .activity-bar,
        .activity-bar-hit:focus-visible .activity-bar {
          filter: brightness(1.15);
        }
        .activity-bar-hit:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
        .activity-tip {
          position: absolute; bottom: calc(100% + 8px); left: 50%; transform: translateX(-50%);
          background: var(--ink); color: var(--surface); border-radius: var(--radius-sm);
          padding: 8px 10px; font-size: 12px; line-height: 1.5; white-space: nowrap;
          box-shadow: 0 4px 16px rgba(0,0,0,0.18); z-index: 10; text-align: center;
          pointer-events: none;
        }
        .activity-tip-sub { opacity: 0.75; }
        .activity-legend {
          display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px;
        }
      `}</style>
    </div>
  );
}
