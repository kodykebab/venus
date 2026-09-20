"""HTML for the service's own pages, in the same design language as the demo.

Deliberately server-rendered with no framework and no build step: these are four
pages, they have to work the instant GitHub redirects someone to them, and a
dashboard that needs a bundler is a dashboard that breaks on deploy day.

Everything interpolated into a page goes through `esc`. Repository names,
account logins and verdicts all originate outside this service.
"""
from __future__ import annotations

import html
import time

STYLES = """
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@500;700;800;900&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

:root {
  --bg: #faf9f7;
  --surface: #ffffff;
  --ink: #14130f;
  --ink-muted: #5c584e;
  --rule: #ddd9cf;
  --accent: #d6300b;
  --accent-ink: #ffffff;
  --good: #0b8f6e;
  --warn: #b26a00;
  --chip-bg: #f1efe8;
  --shadow: 0 1px 2px rgba(20,19,15,.05);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #141412; --surface: #1b1a17; --ink: #f4f2ec; --ink-muted: #a49f92;
    --rule: #34322c; --accent: #e85a38; --accent-ink: #14130f; --good: #22a67f;
    --warn: #d99425; --chip-bg: #232019; --shadow: 0 1px 2px rgba(0,0,0,.4);
  }
}
:root[data-theme="dark"] {
  --bg: #141412; --surface: #1b1a17; --ink: #f4f2ec; --ink-muted: #a49f92;
  --rule: #34322c; --accent: #e85a38; --accent-ink: #14130f; --good: #22a67f;
  --warn: #d99425; --chip-bg: #232019; --shadow: 0 1px 2px rgba(0,0,0,.4);
}

* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font-family: "IBM Plex Sans", -apple-system, BlinkMacSystemFont, sans-serif;
  font-size: 15px; line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}
h1, h2, h3 { font-family: "Archivo", -apple-system, sans-serif; letter-spacing: -0.02em; margin: 0; }
h1 { font-weight: 900; font-size: clamp(28px, 5vw, 42px); line-height: 1.05; }
h2 { font-weight: 800; font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--ink-muted); }
h3 { font-weight: 800; font-size: 19px; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
code, .mono { font-family: "IBM Plex Mono", ui-monospace, monospace; }

.wrap { max-width: 980px; margin: 0 auto; padding: 0 16px; }

header.bar {
  border-bottom: 1px solid var(--rule); background: var(--surface);
  position: sticky; top: 0; z-index: 10;
}
header.bar .wrap { display: flex; align-items: center; gap: 16px; height: 58px; }
.wordmark { font-family: "Archivo"; font-weight: 900; font-size: 17px; letter-spacing: -0.01em; color: var(--ink); }
.wordmark span { color: var(--accent); }
.bar nav { margin-left: auto; display: flex; gap: 18px; align-items: center; font-size: 14px; font-weight: 500; }
.bar nav a { color: var(--ink-muted); }
.bar nav a:hover { color: var(--ink); text-decoration: none; }

main { padding: 40px 0 72px; }
section + section { margin-top: 44px; }
.section-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 14px; }
.section-head .rule { flex: 1; height: 1px; background: var(--rule); }

.card {
  background: var(--surface); border: 1px solid var(--rule);
  border-radius: 6px; box-shadow: var(--shadow);
}
.card-pad { padding: 20px; }

.grid { display: grid; gap: 14px; }
.grid-4 { grid-template-columns: repeat(4, 1fr); }
.grid-3 { grid-template-columns: repeat(3, 1fr); }
.grid-2 { grid-template-columns: repeat(2, 1fr); }
@media (max-width: 820px) {
  .grid-4 { grid-template-columns: repeat(2, 1fr); }
  .grid-3, .grid-2 { grid-template-columns: 1fr; }
}

.stat { background: var(--surface); border: 1px solid var(--rule); border-radius: 6px; padding: 16px; }
.stat-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; color: var(--ink-muted); }
.stat-value { font-family: "Archivo"; font-weight: 900; font-size: 30px; line-height: 1.1; margin-top: 6px; }
.stat-note { font-size: 12.5px; color: var(--ink-muted); margin-top: 2px; }
.stat-value.accent { color: var(--accent); }
.stat-value.good { color: var(--good); }

.chip {
  display: inline-block; padding: 3px 9px; border-radius: 999px;
  background: var(--chip-bg); border: 1px solid var(--rule);
  font-size: 11.5px; font-weight: 600; letter-spacing: 0.02em;
}
.chip.good { color: var(--good); border-color: color-mix(in srgb, var(--good) 35%, var(--rule)); }
.chip.warn { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 35%, var(--rule)); }
.chip.accent { color: var(--accent); border-color: color-mix(in srgb, var(--accent) 35%, var(--rule)); }

.btn {
  display: inline-block; padding: 11px 20px; border-radius: 5px;
  background: var(--accent); color: var(--accent-ink);
  font-weight: 700; font-size: 14.5px; border: 1px solid var(--accent);
}
.btn:hover { text-decoration: none; filter: brightness(1.06); }
.btn.ghost { background: transparent; color: var(--ink); border-color: var(--rule); }

table { width: 100%; border-collapse: collapse; font-size: 14px; }
th {
  text-align: left; padding: 9px 12px; font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.06em; color: var(--ink-muted);
  border-bottom: 1px solid var(--rule); white-space: nowrap;
}
td { padding: 11px 12px; border-bottom: 1px solid var(--rule); vertical-align: middle; }
tr:last-child td { border-bottom: none; }
td.num { font-family: "Archivo"; font-weight: 800; }
.empty { padding: 28px 20px; text-align: center; color: var(--ink-muted); font-size: 14px; }

.muted { color: var(--ink-muted); }
.small { font-size: 13px; }
pre {
  background: var(--chip-bg); border: 1px solid var(--rule); border-radius: 5px;
  padding: 14px 16px; overflow-x: auto; font-size: 13px; line-height: 1.6;
  font-family: "IBM Plex Mono", ui-monospace, monospace; margin: 0;
}
ul.plain { list-style: none; padding: 0; margin: 0; }
ul.plain li { padding: 10px 0; border-bottom: 1px solid var(--rule); display: flex; align-items: center; gap: 10px; }
ul.plain li:last-child { border-bottom: none; }

footer { border-top: 1px solid var(--rule); padding: 24px 0 40px; color: var(--ink-muted); font-size: 13px; }
"""


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def page(title: str, body: str, nav: str = "") -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="color-scheme" content="light dark">
<style>{STYLES}</style>
</head>
<body>
<header class="bar"><div class="wrap">
  <a class="wordmark" href="/">Para<span>Check</span></a>
  <nav>{nav}</nav>
</div></header>
<main class="wrap">{body}</main>
<footer><div class="wrap">
  Parallelism-aware review for EVM contracts &middot;
  <a href="https://github.com/kodyshan/paracheck">Source</a>
</div></footer>
</body>
</html>"""


def section(heading: str, content: str) -> str:
    return f"""<section>
  <div class="section-head"><h2>{esc(heading)}</h2><div class="rule"></div></div>
  {content}
</section>"""


def stat(label: str, value, note: str = "", tone: str = "") -> str:
    note_html = f'<div class="stat-note">{esc(note)}</div>' if note else ""
    return f"""<div class="stat">
  <div class="stat-label">{esc(label)}</div>
  <div class="stat-value {tone}">{esc(value)}</div>
  {note_html}
</div>"""


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
