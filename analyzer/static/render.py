"""Deterministic Markdown rendering of a review report.

This is the no-API-key path: every consumer (CLI, GitHub Action, web UI) can
render a useful review from raw findings alone. The LLM synthesis layer in
analyzer/llm/ is an enhancement on top of this, never a requirement for it.
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


def _score_badge(score: int | None) -> str:
    if score is None:
        return "⚪"
    return "🟢" if score >= 70 else "🟡" if score >= 30 else "🔴"


def render_markdown(report: dict, target: str = "", title: str = "ParaCheck review") -> str:
    lines = [f"### {title}" + (f" — `{target}`" if target else ""), ""]

    if report.get("unanalyzable"):
        lines.append(f"⚠️ **Unanalyzable**: {report.get('reason', 'unknown reason')}")
        return "\n".join(lines)

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
        badge = _score_badge(score)
        lines.append(f"**{contract['contract']}** — {badge} parallelism score **{score}**/100")
        safe = contract.get("safeFunctions") or []
        if safe:
            lines.append(f"- Safe under concurrency: {', '.join(f'`{fn}()`' for fn in safe)}")
    lines.append("")

    findings = report.get("findings") or []
    if findings:
        lines.append("| | Severity | Check | Location | Finding |")
        lines.append("|---|---|---|---|---|")
        for f in findings:
            badge = SEVERITY_BADGE.get(f["severity"], "•")
            loc = f"`{f['file']}:{f['lines'][0]}`" if f.get("file") and f.get("lines") else "—"
            title_cell = f["title"].replace("|", "\\|")
            lines.append(f"| {badge} | {f['severity']} | `{f['check']}` | {loc} | {title_cell} |")
        lines.append("")

        fixes = [f for f in findings if f.get("suggested_fix")]
        if fixes:
            lines.append("<details><summary>Suggested fixes</summary>")
            lines.append("")
            for f in fixes:
                lines.append(f"- **`{f['check']}`** — {f['suggested_fix']}")
            lines.append("")
            lines.append("</details>")

    return "\n".join(lines).rstrip() + "\n"
