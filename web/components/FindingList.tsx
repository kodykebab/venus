import type { FindingDetail } from "@/lib/api";
import { Badge, type Tone } from "./ui";

/**
 * A scan's full findings, in the WHAT / WHY / FIX structure style.md asks
 * for (section 9). A count on the history row answers "how many"; this
 * answers "what, where, why, and what to do about it" - the question a
 * developer actually opens the dashboard to ask, and the reason a bare
 * finding count was never going to be enough.
 *
 * Prioritised, not flattened: critical/high are never visually equal to
 * info/optimization (style.md section 8), so severity groups render as
 * their own labelled blocks in fixed order rather than one undifferentiated
 * list.
 */

const SEVERITY_ORDER = ["critical", "high", "medium", "low", "info", "optimization"];
const SEVERITY_LABEL: Record<string, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  info: "Info",
  optimization: "Optimization",
};
const SEVERITY_TONE: Record<string, Tone> = {
  critical: "critical",
  high: "critical",
  medium: "warn",
  low: "warn",
  info: "",
  optimization: "",
};

export function FindingList({ findings }: { findings: FindingDetail[] }) {
  if (!findings.length) {
    return (
      <div className="state" style={{ padding: "20px 0 4px" }}>
        <p style={{ margin: 0 }}>
          No findings. Nothing here crossed the severity threshold this scan reported at.
        </p>
      </div>
    );
  }

  const bySeverity = new Map<string, FindingDetail[]>();
  for (const finding of findings) {
    const list = bySeverity.get(finding.severity) ?? [];
    list.push(finding);
    bySeverity.set(finding.severity, list);
  }

  return (
    <div className="finding-list">
      {SEVERITY_ORDER.filter((sev) => bySeverity.has(sev)).map((severity) => (
        <div key={severity} className="finding-group">
          <div className="finding-group-label">
            <Badge tone={SEVERITY_TONE[severity]}>
              {SEVERITY_LABEL[severity] ?? severity} &middot; {bySeverity.get(severity)!.length}
            </Badge>
          </div>
          {bySeverity.get(severity)!.map((finding, i) => (
            <Finding key={`${severity}-${i}`} finding={finding} />
          ))}
        </div>
      ))}
      <style>{`
        .finding-list { display: flex; flex-direction: column; gap: 20px; }
        .finding-group-label { margin-bottom: 10px; }
        .finding {
          border: 1px solid var(--line); border-radius: var(--radius);
          background: var(--surface); overflow: hidden;
        }
        .finding + .finding { margin-top: 10px; }
        .finding-head { padding: 14px 16px 0; }
        .finding-title { font-size: 15px; font-weight: 600; margin-top: 4px; }
        .finding-loc {
          font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 12.5px;
          color: var(--ink-3); margin-top: 4px;
        }
        .finding-body { padding: 12px 16px 16px; }
        .finding-why { font-size: 14px; color: var(--ink-2); line-height: 1.6; }
        .finding-fix {
          margin-top: 12px; padding: 10px 12px; border-radius: var(--radius-sm);
          background: var(--surface-2); border: 1px solid var(--line);
          font-size: 13.5px;
        }
        .finding-fix-label {
          font-size: 11px; font-weight: 600; text-transform: uppercase;
          letter-spacing: 0.06em; color: var(--ink-3); margin-bottom: 4px;
        }
      `}</style>
    </div>
  );
}

function Finding({ finding }: { finding: FindingDetail }) {
  const location = finding.file
    ? `${finding.file}${finding.lines?.length ? `:${finding.lines[0]}` : ""}`
    : null;

  return (
    <div className="finding">
      <div className="finding-head">
        <div className="small dim mono">
          {finding.check}
          {finding.confidence ? ` · ${finding.confidence} confidence` : ""}
        </div>
        <div className="finding-title">{finding.title}</div>
        {(location || finding.contract) && (
          <div className="finding-loc">
            {finding.contract ? `${finding.contract}` : ""}
            {finding.contract && location ? " · " : ""}
            {location ?? ""}
          </div>
        )}
      </div>
      <div className="finding-body">
        {finding.description && <p className="finding-why">{finding.description}</p>}
        {finding.suggested_fix && (
          <div className="finding-fix">
            <div className="finding-fix-label">Fix</div>
            <div>{finding.suggested_fix}</div>
          </div>
        )}
      </div>
    </div>
  );
}
