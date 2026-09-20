"""The design system, and the HTML shell every page is built from.

Implements style.md: Swiss-inspired technical software - precise, quiet,
restrained. One accent colour, 1px borders, 4-8px radii, whitespace doing the
work. No gradients, no glow, no glassmorphism.

Server-rendered with no framework and no build step, because these pages have to
work the instant GitHub redirects someone to them, and a dashboard that needs a
bundler is a dashboard that breaks on deploy day.

Everything interpolated goes through `esc`. Repository names, account logins and
verdicts all originate outside this service.
"""
from __future__ import annotations

import html
import time

# Tokens are declared once here and never overridden inline with raw hex.
# style.md 51.11: do not introduce a new colour without checking the system.
STYLES = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  /* Surfaces */
  --bg: #F7F7F5;
  --surface: #FFFFFF;
  --surface-2: #F1F1EE;

  /* Text */
  --ink: #111111;
  --ink-2: #5F5F5A;
  --ink-3: #85857F;

  /* Lines */
  --line: #DCDCD6;
  --line-strong: #BDBDB6;

  /* Exactly one accent, used for action and nothing else. */
  --accent: #1D4ED8;
  --accent-hover: #1E40AF;
  --accent-ink: #FFFFFF;

  /* Severity. Small signals, never large backgrounds. */
  --ok: #16803C;
  --warn: #A16207;
  --critical: #B42318;

  --radius: 6px;
  --radius-sm: 4px;

  /* Baseline rhythm */
  --gap: 16px;
  --section-gap: 120px;
  --measure: 68ch;

  --z-header: 20;
  --z-overlay: 50;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0E0E0D;
    --surface: #161615;
    --surface-2: #1D1D1B;
    --ink: #F4F4F1;
    --ink-2: #A8A8A1;
    --ink-3: #7C7C75;
    --line: #2A2A27;
    --line-strong: #3C3C38;
    --accent: #5B8DEF;
    --accent-hover: #7BA4F3;
    --accent-ink: #0E0E0D;
    --ok: #3FA76B;
    --warn: #D0A030;
    --critical: #E06B5E;
  }
}
:root[data-theme="dark"] {
  --bg: #0E0E0D; --surface: #161615; --surface-2: #1D1D1B;
  --ink: #F4F4F1; --ink-2: #A8A8A1; --ink-3: #7C7C75;
  --line: #2A2A27; --line-strong: #3C3C38;
  --accent: #5B8DEF; --accent-hover: #7BA4F3; --accent-ink: #0E0E0D;
  --ok: #3FA76B; --warn: #D0A030; --critical: #E06B5E;
}

*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 16px;
  line-height: 1.55;
  font-feature-settings: "cv05" 1, "ss01" 1;
  -webkit-font-smoothing: antialiased;
}

h1, h2, h3, h4 { margin: 0; font-weight: 600; letter-spacing: -0.021em; }
h1 { font-size: clamp(36px, 6.4vw, 72px); line-height: 1.0; letter-spacing: -0.035em; }
h2 { font-size: clamp(28px, 3.6vw, 40px); line-height: 1.12; letter-spacing: -0.028em; }
h3 { font-size: 18px; line-height: 1.35; }
p { margin: 0; }

a { color: var(--accent); text-decoration: none; }
a:hover { color: var(--accent-hover); text-decoration: underline; }

code, .mono, pre {
  font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  font-variant-ligatures: none;
}

/* Focus is never removed, only shaped. style.md 45. */
:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  border-radius: var(--radius-sm);
}
:focus:not(:focus-visible) { outline: none; }

.wrap { max-width: 1240px; margin: 0 auto; padding: 0 32px; }
@media (max-width: 720px) { .wrap { padding: 0 20px; } }

/* --- Header ------------------------------------------------------------- */

header.bar {
  border-bottom: 1px solid var(--line);
  background: var(--surface);
  position: sticky;
  top: 0;
  z-index: var(--z-header);
}
header.bar .wrap { display: flex; align-items: center; gap: 24px; height: 56px; }
.wordmark {
  font-weight: 600; font-size: 15px; letter-spacing: -0.02em; color: var(--ink);
}
.wordmark:hover { text-decoration: none; color: var(--ink); }
.bar nav {
  margin-left: auto; display: flex; gap: 20px; align-items: center;
  font-size: 14px; font-weight: 500;
}
.bar nav a { color: var(--ink-2); }
.bar nav a:hover { color: var(--ink); text-decoration: none; }
.bar nav a.btn { color: var(--accent-ink); }
@media (max-width: 680px) {
  .bar nav a:not(.btn) { display: none; }
}

main { padding: 56px 0 96px; }
.section { margin-top: var(--section-gap); }
@media (max-width: 860px) { :root { --section-gap: 80px; } }

/* A quiet label above a block, on the same left edge as its content. */
.eyebrow {
  font-size: 12px; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--ink-3);
  display: flex; align-items: center; gap: 12px; margin-bottom: 20px;
}
.eyebrow::after { content: ""; flex: 1; height: 1px; background: var(--line); }

.lede { font-size: 17px; color: var(--ink-2); max-width: var(--measure); }
.muted { color: var(--ink-2); }
.dim { color: var(--ink-3); }
.small { font-size: 13px; }

/* --- Surfaces ----------------------------------------------------------- */

.panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}
.panel-pad { padding: 24px; }
@media (max-width: 720px) { .panel-pad { padding: 18px; } }

.grid { display: grid; gap: var(--gap); }
.grid-2 { grid-template-columns: repeat(2, 1fr); }
.grid-3 { grid-template-columns: repeat(3, 1fr); }
.grid-4 { grid-template-columns: repeat(4, 1fr); }
@media (max-width: 900px) { .grid-4 { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 760px) { .grid-2, .grid-3 { grid-template-columns: 1fr; } }
@media (max-width: 460px) { .grid-4 { grid-template-columns: 1fr; } }

/* --- Metrics ------------------------------------------------------------ */

.stat { border-left: 1px solid var(--line); padding: 2px 0 2px 16px; }
.stat-label {
  font-size: 12px; font-weight: 500; color: var(--ink-3);
  letter-spacing: 0.02em;
}
.stat-value {
  font-size: 30px; font-weight: 600; letter-spacing: -0.03em;
  line-height: 1.15; margin-top: 6px; font-variant-numeric: tabular-nums;
}
.stat-note { font-size: 13px; color: var(--ink-3); margin-top: 2px; }
.stat-value.is-accent { color: var(--accent); }
.stat-value.is-ok { color: var(--ok); }
.stat-value.is-critical { color: var(--critical); }

/* --- Badges: icon + label + colour, never colour alone (style.md 45) ---- */

.badge {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 3px 9px; border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  font-size: 12px; font-weight: 500; color: var(--ink-2);
  white-space: nowrap;
}
.badge .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; flex: none; }
.badge.is-ok { color: var(--ok); border-color: color-mix(in srgb, var(--ok) 32%, var(--line)); }
.badge.is-warn { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 32%, var(--line)); }
.badge.is-critical { color: var(--critical); border-color: color-mix(in srgb, var(--critical) 32%, var(--line)); }
.badge.is-accent { color: var(--accent); border-color: color-mix(in srgb, var(--accent) 32%, var(--line)); }

/* --- Buttons ------------------------------------------------------------ */

.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  min-height: 44px; padding: 0 18px;           /* 44px: touch target minimum */
  border-radius: var(--radius);
  border: 1px solid var(--accent);
  background: var(--accent); color: var(--accent-ink);
  font-family: inherit; font-size: 14px; font-weight: 600; letter-spacing: -0.006em;
  cursor: pointer;
  transition: background-color 160ms ease, border-color 160ms ease, color 160ms ease;
  text-decoration: none;
}
.btn:hover { background: var(--accent-hover); border-color: var(--accent-hover); color: var(--accent-ink); text-decoration: none; }
.btn:disabled, .btn[aria-disabled="true"] { opacity: .55; cursor: not-allowed; }

.btn.secondary {
  background: var(--surface); color: var(--ink); border-color: var(--line-strong);
}
.btn.secondary:hover { background: var(--surface-2); color: var(--ink); border-color: var(--ink-3); }

.btn.small { min-height: 34px; padding: 0 12px; font-size: 13px; }

.btn-row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }

/* --- Inputs ------------------------------------------------------------- */

.field {
  width: 100%; min-height: 44px; padding: 10px 12px;
  border: 1px solid var(--line-strong); border-radius: var(--radius);
  background: var(--surface); color: var(--ink);
  font-family: inherit; font-size: 14px;
}
.field.mono { font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 13px; }
.field::placeholder { color: var(--ink-3); }
.field:focus-visible { border-color: var(--accent); }
label.label {
  display: block; font-size: 13px; font-weight: 500;
  color: var(--ink-2); margin-bottom: 6px;
}

/* --- Tables ------------------------------------------------------------- */

table { width: 100%; border-collapse: collapse; font-size: 14px; }
th {
  text-align: left; padding: 10px 14px;
  font-size: 12px; font-weight: 500; color: var(--ink-3); letter-spacing: 0.02em;
  border-bottom: 1px solid var(--line); white-space: nowrap;
}
td { padding: 13px 14px; border-bottom: 1px solid var(--line); vertical-align: middle; }
tr:last-child td { border-bottom: none; }
td.num { font-variant-numeric: tabular-nums; }

/* Tables become cards on a phone rather than shrinking past legibility. */
@media (max-width: 720px) {
  table.responsive, table.responsive tbody, table.responsive tr, table.responsive td { display: block; width: 100%; }
  table.responsive thead { display: none; }
  table.responsive tr { border-bottom: 1px solid var(--line); padding: 12px 0; }
  table.responsive tr:last-child { border-bottom: none; }
  table.responsive td { border: none; padding: 3px 14px; }
  table.responsive td[data-label]::before {
    content: attr(data-label) "  ";
    color: var(--ink-3); font-size: 12px;
  }
}

/* --- Lists -------------------------------------------------------------- */

ul.rows { list-style: none; padding: 0; margin: 0; }
ul.rows li {
  padding: 12px 0; border-bottom: 1px solid var(--line);
  display: flex; align-items: center; gap: 12px; font-size: 14px;
}
ul.rows li:last-child { border-bottom: none; }
ul.rows li .spacer { margin-left: auto; }

/* --- Code --------------------------------------------------------------- */

pre {
  background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 14px 16px;
  overflow-x: auto; line-height: 1.6; margin: 0;
}
code.inline {
  background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--radius-sm); padding: 1px 5px;
}

/* --- Empty and error states (style.md 28, 29) --------------------------- */

.state { padding: 40px 24px; text-align: center; }
.state h3 { margin-bottom: 8px; }
.state p { color: var(--ink-2); font-size: 14px; max-width: 46ch; margin: 0 auto; }
.state .btn-row { justify-content: center; margin-top: 20px; }
.state.is-error { text-align: left; }
.state.is-error .btn-row { justify-content: flex-start; }

.notice {
  border: 1px solid var(--line); border-left-width: 3px;
  border-radius: var(--radius); padding: 14px 16px; font-size: 14px;
  background: var(--surface);
}
.notice.is-ok { border-left-color: var(--ok); }
.notice.is-error { border-left-color: var(--critical); }
.notice.is-warn { border-left-color: var(--warn); }

footer {
  border-top: 1px solid var(--line); margin-top: var(--section-gap);
  padding: 28px 0 48px; color: var(--ink-3); font-size: 13px;
}
footer .wrap { display: flex; gap: 20px; flex-wrap: wrap; align-items: center; }
footer a { color: var(--ink-2); }
footer .spacer { margin-left: auto; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
"""


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def page(title: str, body: str, nav: str = "", description: str = "") -> str:
    meta = (f'<meta name="description" content="{esc(description)}">'
            if description else "")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
{meta}
<meta name="color-scheme" content="light dark">
<style>{STYLES}</style>
</head>
<body>
<a class="skip" href="#main" style="position:absolute;left:-9999px">Skip to content</a>
<header class="bar"><div class="wrap">
  <a class="wordmark" href="/">ParaCheck</a>
  <nav>{nav}</nav>
</div></header>
<main id="main" class="wrap">{body}</main>
<footer><div class="wrap">
  <span>ParaCheck</span>
  <span class="spacer"></span>
  <a href="/pricing">Pricing</a>
  <a href="https://github.com/kodyshan/paracheck">Source</a>
</div></footer>
</body>
</html>"""


def section(eyebrow: str, content: str, first: bool = False) -> str:
    """A labelled block. `first` drops the top margin for the page's opening
    section, so the header doesn't get pushed down by a full section gap."""
    style = ' style="margin-top:0"' if first else ""
    return f"""<section class="section"{style}>
  <h2 class="eyebrow">{esc(eyebrow)}</h2>
  {content}
</section>"""


def stat(label: str, value, note: str = "", tone: str = "") -> str:
    note_html = f'<div class="stat-note">{esc(note)}</div>' if note else ""
    tone_class = f" is-{tone}" if tone else ""
    return f"""<div class="stat">
  <div class="stat-label">{esc(label)}</div>
  <div class="stat-value{tone_class}">{esc(value)}</div>
  {note_html}
</div>"""


def badge(text: str, tone: str = "") -> str:
    """Severity and status carry a dot, a word and a colour - never colour on
    its own, which is invisible to anyone who can't distinguish it."""
    tone_class = f" is-{tone}" if tone else ""
    return f'<span class="badge{tone_class}"><span class="dot"></span>{esc(text)}</span>'


def empty_state(heading: str, body: str, action: str = "") -> str:
    """style.md 28: never "nothing here yet". Say what the surface is, why it is
    empty, and what to do next."""
    action_html = f'<div class="btn-row">{action}</div>' if action else ""
    return f"""<div class="panel"><div class="state">
      <h3>{esc(heading)}</h3>
      <p>{esc(body)}</p>
      {action_html}
    </div></div>"""


def ago(timestamp: int | None) -> str:
    """Relative time, because "3h ago" answers "is this thing running?" and an
    ISO timestamp makes the reader do the subtraction."""
    if not timestamp:
        return "-"
    seconds = max(int(time.time()) - int(timestamp), 0)
    for size, unit in ((60, "s"), (60, "m"), (24, "h"), (365, "d")):
        if seconds < size:
            return f"{seconds}{unit} ago"
        seconds //= size
    return f"{seconds}y ago"


def until(timestamp: int | None) -> str:
    """How long until something becomes available again - the other half of a
    quota message, so "you're out" can also say "until when"."""
    if not timestamp:
        return "-"
    seconds = max(int(timestamp) - int(time.time()), 0)
    if seconds < 3600:
        return f"{max(seconds // 60, 1)}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"
