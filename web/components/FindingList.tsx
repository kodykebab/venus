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

const PROVEN_TIERS = new Set(["A", "B"]);
const isProven = (f: FindingDetail) => PROVEN_TIERS.has(f.evidence ?? "D");

function bySeverity(findings: FindingDetail[]): [string, FindingDetail[]][] {
  const map = new Map<string, FindingDetail[]>();
  for (const finding of findings) {
    const list = map.get(finding.severity) ?? [];
    list.push(finding);
    map.set(finding.severity, list);
  }
  return SEVERITY_ORDER.filter((sev) => map.has(sev)).map((sev) => [sev, map.get(sev)!]);
}

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

  // Evidence is the primary split, not severity: a developer should see what
  // actually reproduces before any pattern-matched lead, however severe the
  // lead looks. Only proven findings ever block a merge upstream, so the UI
  // makes the same distinction the check run does.
  const proven = findings.filter(isProven);
  const unproven = findings.filter((f) => !isProven(f));

  return (
    <div className="finding-list">
      {proven.length > 0 && (
        <div className="finding-section">
          <div className="finding-section-head">
            <Badge tone="accent">
              Proven &middot; {proven.length}
            </Badge>
            <span className="finding-section-note">
              Each reproduces: the test fails on this code and passes once fixed.
            </span>
          </div>
          {proven.map((finding, i) => (
            <Finding key={`proven-${i}`} finding={finding} />
          ))}
        </div>
      )}

      {unproven.length > 0 && (
        <div className="finding-section">
          <div className="finding-section-head">
            <Badge tone="">
              Unproven leads &middot; {unproven.length}
            </Badge>
            <span className="finding-section-note">
              Pattern matches, not reproduced. These never block a merge.
            </span>
          </div>
          {bySeverity(unproven).map(([severity, group]) => (
            <div key={severity} className="finding-group">
              <div className="finding-group-label">
                <Badge tone={SEVERITY_TONE[severity]}>
                  {SEVERITY_LABEL[severity] ?? severity} &middot; {group.length}
                </Badge>
              </div>
              {group.map((finding, i) => (
                <Finding key={`${severity}-${i}`} finding={finding} />
              ))}
            </div>
          ))}
        </div>
      )}
      <style>{`
        .finding-list { display: flex; flex-direction: column; gap: 28px; }
        .finding-section { display: flex; flex-direction: column; gap: 20px; }
        .finding-section-head {
          display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
        }
        .finding-section-note { font-size: 13px; color: var(--ink-3); }
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
        .finding-why-pre {
          font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 12.5px;
          color: var(--ink-2); line-height: 1.6; white-space: pre-wrap; word-break: break-word;
          background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--radius-sm);
          padding: 10px 12px; margin: 0;
        }
        .finding-fix {
          margin-top: 12px; padding: 10px 12px; border-radius: var(--radius-sm);
          background: var(--surface-2); border: 1px solid var(--line);
          font-size: 13.5px;
        }
        .finding-fix-label {
          font-size: 11px; font-weight: 600; text-transform: uppercase;
          letter-spacing: 0.06em; color: var(--ink-3); margin-bottom: 4px;
        }
        .finding-repro {
          margin-top: 12px; border-radius: var(--radius-sm);
          border: 1px solid color-mix(in srgb, var(--accent) 32%, var(--line));
          overflow: hidden;
        }
        .finding-repro-label {
          font-size: 11px; font-weight: 600; text-transform: uppercase;
          letter-spacing: 0.06em; color: var(--accent);
          padding: 8px 12px; background: color-mix(in srgb, var(--accent) 8%, var(--surface));
        }
        .finding-repro-cmd {
          font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 12.5px;
          color: var(--ink); background: var(--surface-2); margin: 0;
          padding: 10px 12px; white-space: pre-wrap; word-break: break-all;
        }
        .finding-repro-flip {
          font-size: 12px; color: var(--ink-3);
          padding: 0 12px 10px; background: var(--surface-2); margin: 0;
        }
      `}</style>
    </div>
  );
}

/**
 * Slither's own detectors write their description as a multi-line,
 * tab-indented technical dump - meant to be read as fixed-width text, not
 * prose. A plain <p> collapses every newline and tab into nothing (that is
 * what HTML does with whitespace by default), turning a structured trace
 * into one dense run-on paragraph. ParaCheck's own findings (hot-slot, the
 * parallelism classifier) are hand-written prose and never take this path -
 * only Slither-sourced, genuinely multi-line descriptions do.
 */
function FindingWhy({ finding }: { finding: FindingDetail }) {
  const isTechnicalDump =
    finding.source === "slither" && /[\n\t]/.test(finding.description);

  if (isTechnicalDump) {
    return <pre className="finding-why-pre">{finding.description}</pre>;
  }
  return <p className="finding-why">{finding.description}</p>;
}

/**
 * The reproduce block for a proven finding. The command is the product's whole
 * promise made concrete: the reader can paste it and watch the exploit test
 * fail on this code, then pass once the fix is in. No trust required.
 */
function Reproduce({ detail }: { detail: NonNullable<FindingDetail["evidence_detail"]> }) {
  return (
    <div className="finding-repro">
      <div className="finding-repro-label">Reproduce</div>
      <pre className="finding-repro-cmd">{detail.command}</pre>
      {detail.vulnerable && detail.patched && (
        <p className="finding-repro-flip">
          Fails on this branch ({detail.vulnerable}), passes against the fix ({detail.patched}).
        </p>
      )}
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
        {finding.description && <FindingWhy finding={finding} />}
        {isProven(finding) && finding.evidence_detail?.command && (
          <Reproduce detail={finding.evidence_detail} />
        )}
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
