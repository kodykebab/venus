"""Deterministic Markdown rendering of a review report.

This is the no-API-key path: every consumer (CLI, GitHub Action, web UI) can
render a useful review from raw findings alone. The LLM synthesis layer in
analyzer/llm/ is an enhancement on top of this, never a requirement for it.

Findings render in the WHAT / WHY / FIX shape, not a compressed table: a
severity count and a one-line title answers "how many", not "what do I do
about it" - and the Check Run summary is the first, and for most people the
only, place this ever gets read. Grouped and ordered by severity rather than
flattened, because a critical finding and an optimization nit are not the
same amount of attention, and treating them as equal rows makes the real
issue easy to miss in a long list (style.md section 8).
"""
from __future__ import annotations

SEVERITY_BADGE = {
    "critical": "🔴",
    "high": "🔴",
    "medium": "🟠",
    "low": "🟡",
    "info": "🔵",
    "optimization": "⚪",
}

SEVERITY_LABEL = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "info": "Info",
    "optimization": "Optimization",
}

SEVERITY_ORDER = ["critical", "high", "medium", "low", "info", "optimization"]

# Evidence tiers (kept local so this deterministic renderer has no import
# coupling). Only A and B are proven: they lead the report and may block a
# merge. C and D are collapsed and never block; D is labelled unproven.
_PROVEN_TIERS = {"A", "B"}
_EVIDENCE_LABEL = {
    "A": "proven with an exploit test",
    "B": "proven with a symbolic counterexample",
    "C": "reachable",
    "D": "unproven",
}


def _is_proven(finding: dict) -> bool:
    return finding.get("evidence", "D") in _PROVEN_TIERS


def _render_proof(finding: dict) -> list[str]:
    """The reproduce block for a proven finding: the reader can run it."""
    detail = finding.get("evidence_detail") or {}
    command = detail.get("command")
    if not command:
        return []
    tier = finding.get("evidence", "D")
    lines = [f"**Reproduce** ({_EVIDENCE_LABEL.get(tier, 'proven')}):", "", "```bash", command, "```"]
    vuln, patched = detail.get("vulnerable"), detail.get("patched")
    if vuln and patched:
        lines.append(f"_Fails on this branch ({vuln}), passes against the fix ({patched})._")
    lines.append("")
    return lines

# Below this severity, a finding gets its title and location but is folded
# into a collapsed group rather than shown open - past a certain point, equal
# weight for every finding stops being readable and starts being noise.
OPEN_BY_DEFAULT = {"critical", "high", "medium"}


def _score_badge(score: int | None) -> str:
    if score is None:
        return "⚪"
    return "🟢" if score >= 70 else "🟡" if score >= 30 else "🔴"


def _location(finding: dict) -> str:
    file = finding.get("file")
    lines = finding.get("lines") or []
    if not file:
        return ""
    return f"`{file}:{lines[0]}`" if lines else f"`{file}`"


def _render_finding(finding: dict, heading: str = "####") -> list[str]:
    """One finding, in full: check id, location, the WHY, and the FIX when
    the analyzer has one. `heading` controls nesting depth so this reads
    correctly whether it is a top-level block or inside a collapsed group."""
    lines: list[str] = []
    where = _location(finding)
    contract = finding.get("contract")
    meta = " · ".join(p for p in (contract, where) if p)

    lines.append(f"{heading} {finding['title']}")
    if meta:
        lines.append(f"*{meta}* · `{finding['check']}`")
    lines.append("")
    description = finding.get("description") or ""
    if description:
        if finding.get("source") == "slither" and ("\n" in description or "\t" in description):
            # Slither's own detectors write their description as a multi-line,
            # tab-indented technical dump - meant to be read as fixed-width
            # text, not prose. Left as-is it renders as one unpredictable
            # run-on line or two in Markdown; a fence keeps the structure the
            # detector actually intended. ParaCheck's own findings (hot-slot,
            # the parallelism classifier) are hand-written prose and never
            # take this path.
            lines.append("```")
            lines.append(description.replace("\t", "  "))
            lines.append("```")
        else:
            lines.append(description)
        lines.append("")
    lines.extend(_render_proof(finding))
    if finding.get("suggested_fix"):
        lines.append(f"**Fix:** {finding['suggested_fix']}")
        lines.append("")
    return lines


def render_markdown(report: dict, target: str = "", title: str = "ParaCheck review") -> str:
    lines = [f"### {title}" + (f" — `{target}`" if target else ""), ""]

    if report.get("unanalyzable"):
        lines.append(f"⚠️ **Unanalyzable**: {report.get('reason', 'unknown reason')}")
        return "\n".join(lines)

    chain = report.get("chain") or {}
    if chain:
        note = "" if chain.get("parallelismAnalysisRan") else \
            " — sequential execution, so parallelism analysis was skipped"
        lines.append(f"_Target chain: **{chain.get('name', 'unknown')}**{note}._")
        lines.append("")

    summary = report.get("summary") or {}
    counts = summary.get("bySeverity") or {}
    if counts:
        parts = [f"{SEVERITY_BADGE.get(sev, '•')} {n} {sev}" for sev, n in counts.items()]
        lines.append(f"**{summary.get('totalFindings', 0)} findings** — " + ", ".join(parts))
    else:
        lines.append("**No findings.**")
    lines.append("")

    for contract in report.get("contracts", []):
        score = contract.get("parallelismScore")
        if score is None:
            # Parallelism analysis didn't run for this chain, so "safe under
            # concurrency" would be claiming something we didn't check.
            lines.append(f"**{contract['contract']}**")
            continue
        lines.append(
            f"**{contract['contract']}** — {_score_badge(score)} parallelism score **{score}**/100"
        )
        safe = contract.get("safeFunctions") or []
        if safe:
            lines.append(f"- Safe under concurrency: {', '.join(f'`{fn}()`' for fn in safe)}")
    lines.append("")

    findings = report.get("findings") or []
    if not findings:
        return "\n".join(lines).rstrip() + "\n"

    # The primary split is evidence, not severity. Proven findings (a failing
    # exploit test, a symbolic counterexample) lead the report and are the only
    # ones allowed to block a merge. Everything else is a lead: real signal for
    # a human sweeping the code, but it never interrupts and it says so.
    proven = [f for f in findings if _is_proven(f)]
    unproven = [f for f in findings if not _is_proven(f)]

    if proven:
        noun = "finding" if len(proven) == 1 else "findings"
        lines.append(f"### ✅ {len(proven)} proven {noun}")
        lines.append("")
        lines.append("_Each of these reproduces: the test below fails on this code and passes once fixed._")
        lines.append("")
        for finding in proven:
            lines.extend(_render_finding(finding, heading="####"))

    if unproven:
        lines.extend(_render_unproven(unproven, collapsed=bool(proven)))

    return "\n".join(lines).rstrip() + "\n"


def _render_unproven(findings: list[dict], collapsed: bool) -> list[str]:
    """The leads: grouped by severity, and folded away behind a summary once
    there is proven work above them competing for the reader's attention."""
    lines: list[str] = []
    by_severity: dict[str, list[dict]] = {}
    for finding in findings:
        by_severity.setdefault(finding["severity"], []).append(finding)

    header = f"Leads &amp; notes ({len(findings)})"
    if collapsed:
        lines.append("<details>")
        lines.append(f"<summary>{header} — not proven exploitable, never blocking</summary>")
        lines.append("")
    else:
        lines.append(f"### Leads &amp; notes ({len(findings)})")
        lines.append("")
        lines.append("_Pattern matches and compatibility notes. Not proven exploitable, so nothing here blocks a merge._")
        lines.append("")

    for severity in SEVERITY_ORDER:
        group = by_severity.get(severity)
        if not group:
            continue
        label = f"{SEVERITY_BADGE.get(severity, '•')} {SEVERITY_LABEL.get(severity, severity)} ({len(group)})"
        lines.append(f"#### {label}")
        lines.append("")
        for finding in group:
            lines.extend(_render_finding(finding, heading="#####"))

    if collapsed:
        lines.append("</details>")
        lines.append("")
    return lines
