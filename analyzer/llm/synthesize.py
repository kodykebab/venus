"""Turns raw analyzer findings into a review a human would actually want to read.

This is the layer that separates "a linter that prints JSON" from a reviewer:
the static analyzers decide *what is true*, this decides *what is worth saying*,
in what order, and why it matters for this specific contract.

Degrades gracefully: with no API credentials configured it returns None and the
caller falls back to analyzer/static/render.py's deterministic Markdown. A
missing key must never break a CI run.
"""
from __future__ import annotations

import json
import os

from pydantic import BaseModel, Field

MODEL = "claude-opus-5"

# Kept byte-stable and sent first so it caches across every PR the service reviews.
SYSTEM_PROMPT = """You are reviewing a change to an EVM smart contract, the way a \
senior protocol engineer reviews a colleague's pull request.

You are given findings from static analyzers. The analyzers decide what is true; \
you decide what is worth saying.

Rules:
- Only discuss findings that appear in the input. Never invent an issue, a line \
number, or a file. If something looks suspicious but isn't in the findings, don't \
mention it.
- Prioritise ruthlessly. A reviewer who flags everything gets ignored. Lead with \
what could lose money or break under load; drop noise entirely rather than listing \
it for completeness.
- Explain why a finding matters *for this contract*, in terms of what actually \
happens at runtime. Do not restate the analyzer's generic description.
- Contended storage slots ("hot-slot") are a throughput problem specific to chains \
with parallel execution: concurrent transactions touching the same slot conflict \
and get re-executed serially, so the contract silently loses the throughput the \
chain exists to provide. Treat it as a real design finding, not a style nit.
- Be concrete and brief. No preamble, no praise padding, no restating the diff.
- Write for someone who knows Solidity. Don't explain what reentrancy is.

Verdict guidance:
- "request_changes" only for findings that can lose funds or lock the contract.
- "comment" when there is real feedback worth acting on but nothing dangerous.
- "approve" when findings are informational only, or there are none."""


class ReviewComment(BaseModel):
    file: str = Field(description="File path exactly as given in the finding.")
    line: int = Field(description="Line number from the finding. Never guess one.")
    severity: str = Field(description="critical, high, medium, low, info, or optimization.")
    title: str = Field(description="One short line naming the problem.")
    body: str = Field(description="Why it matters here and what to do. 1-3 sentences.")


class SynthesizedReview(BaseModel):
    summary: str = Field(description="2-4 sentences: what this code does and the main risk.")
    verdict: str = Field(description="approve, comment, or request_changes.")
    comments: list[ReviewComment] = Field(description="Only findings worth a reviewer's attention.")


def credentials_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _build_user_message(report: dict, diff: str | None, source: str | None) -> str:
    parts = []
    if diff:
        parts.append("## The change under review (unified diff)\n\n```diff\n" + diff.strip() + "\n```")
    if source:
        parts.append("## Full current source\n\n```solidity\n" + source.strip() + "\n```")

    contracts = report.get("contracts") or []
    if contracts:
        parts.append(
            "## Parallelism analysis\n\n"
            + json.dumps(contracts, indent=2, sort_keys=True)
            + "\n\nparallelismScore is the share of state-changing external functions "
            "that touch no contended slot (0-100, higher is better)."
        )

    parts.append(
        "## Analyzer findings\n\n"
        + json.dumps(report.get("findings") or [], indent=2, sort_keys=True)
    )
    parts.append("Review this change.")
    return "\n\n".join(parts)


def synthesize_review(
    report: dict,
    diff: str | None = None,
    source: str | None = None,
    model: str = MODEL,
    client=None,
) -> SynthesizedReview | None:
    """Returns a prioritized review, or None if synthesis is unavailable.

    None is a normal outcome (no credentials, API failure) - callers fall back to
    deterministic rendering rather than failing the run."""
    if report.get("unanalyzable"):
        return None
    if client is None and not credentials_available():
        return None

    import anthropic  # imported lazily so the analyzers work without the SDK installed

    client = client or anthropic.Anthropic()

    try:
        response = client.messages.parse(
            model=model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": _build_user_message(report, diff, source)}],
            output_format=SynthesizedReview,
        )
    except anthropic.AuthenticationError:
        print("paracheck: Anthropic credentials rejected - falling back to raw findings.")
        return None
    except anthropic.RateLimitError:
        print("paracheck: rate limited by the Anthropic API - falling back to raw findings.")
        return None
    except anthropic.APIStatusError as exc:
        print(f"paracheck: Anthropic API error {exc.status_code} - falling back to raw findings.")
        return None
    except anthropic.APIConnectionError:
        print("paracheck: could not reach the Anthropic API - falling back to raw findings.")
        return None

    if response.stop_reason == "refusal":
        print("paracheck: model declined to review this input - falling back to raw findings.")
        return None

    return response.parsed_output


VERDICT_BADGE = {
    "approve": "✅ Approve",
    "comment": "💬 Comment",
    "request_changes": "🛑 Request changes",
}

SEVERITY_BADGE = {
    "critical": "🔴", "high": "🔴", "medium": "🟠",
    "low": "🟡", "info": "🔵", "optimization": "⚪",
}


def render_synthesized(review: SynthesizedReview, target: str = "") -> str:
    """Markdown for a PR comment, from a synthesized review."""
    header = "### ParaCheck review" + (f" — `{target}`" if target else "")
    lines = [header, "", f"**{VERDICT_BADGE.get(review.verdict, review.verdict)}**", "", review.summary, ""]

    for comment in review.comments:
        badge = SEVERITY_BADGE.get(comment.severity, "•")
        lines.append(f"{badge} **{comment.title}** — `{comment.file}:{comment.line}`")
        lines.append("")
        lines.append(comment.body)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
