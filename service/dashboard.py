"""The pages a human looks at: the landing page and the installation dashboard.

Kept out of app.py so the routes stay readable - app.py should show what the
service does, not how a table gets rendered.

The dashboard's job is to answer, without anyone opening a log: is this thing
running, what has it reviewed, what did it find, and why did it behave the way
it did on my last pull request. Everything interpolated goes through ui.esc;
repository names and account logins come from GitHub, not from us.
"""
from __future__ import annotations

import ui


def landing(chain: str, trial_reviews: int) -> str:
    """Someone arriving here usually got a link from a teammate and knows
    nothing about the tool, so it leads with the problem, not the feature."""
    what_lands = """
    <div class="grid grid-3">
      <div class="card card-pad">
        <h3>Contended slots</h3>
        <p class="muted small">Which state variables serialize your transactions, which
        functions touch them, and what a per-user or sharded layout would change.</p>
      </div>
      <div class="card card-pad">
        <h3>The usual security pass</h3>
        <p class="muted small">Slither's full detector set, deduplicated, ranked by
        severity, and annotated on the diff rather than dumped in a comment.</p>
      </div>
      <div class="card card-pad">
        <h3>Only what you changed</h3>
        <p class="muted small">Findings are scoped to the files the pull request touches.
        An inherited backlog in code nobody edited isn't review feedback.</p>
      </div>
    </div>"""

    how = """
    <div class="card card-pad">
      <ul class="plain">
        <li><span class="chip">1</span> Install the app on the repositories you pick. There is nothing else to configure.</li>
        <li><span class="chip">2</span> Open a pull request that touches a <code>.sol</code> file.</li>
        <li><span class="chip">3</span> ParaCheck checks the branch out, installs its dependencies, compiles and analyzes it.</li>
        <li><span class="chip">4</span> A Check Run appears on the pull request with inline annotations - and can block the merge.</li>
      </ul>
    </div>"""

    chain_note = f"""
    <div class="card card-pad">
      <p class="muted small" style="margin:0">
        Parallelism findings only mean something on a chain that executes in parallel,
        so they're gated on the target chain instead of being reported everywhere as
        noise. This deployment reviews for <code>{ui.esc(chain)}</code>. Point it at a
        sequential chain and the security analysis still runs - the contention section
        is simply left out.
      </p>
    </div>"""

    body = f"""
    <section style="padding:28px 0 4px">
      <span class="chip accent">GitHub App</span>
      <h1 style="margin-top:16px;max-width:15ch">Storage conflicts, caught in review.</h1>
      <p class="muted" style="max-width:60ch;font-size:17px;margin-top:16px">
        On a parallel-execution chain, two transactions that touch the same storage slot
        can't run at the same time - one is thrown away and re-executed. That cost is
        decided when the contract is written and it is invisible in a normal diff.
        ParaCheck reviews every pull request and tells you which slots will contend.
      </p>
      <p style="margin-top:26px;display:flex;gap:10px;flex-wrap:wrap">
        <a class="btn" href="/install">Add to GitHub</a>
        <a class="btn ghost" href="https://github.com/kodyshan/paracheck">Read the source</a>
      </p>
      <p class="small muted" style="margin-top:14px">
        Free for your first {ui.esc(trial_reviews)} reviews. No card, no config file.
      </p>
    </section>
    {ui.section("What lands on the pull request", what_lands)}
    {ui.section("How it works", how)}
    {ui.section("Chain-aware by design", chain_note)}"""

    return ui.page(
        "ParaCheck - parallelism-aware review for EVM contracts",
        body,
        nav='<a href="https://github.com/kodyshan/paracheck">GitHub</a>'
            '<a class="btn" href="/install">Add to GitHub</a>',
    )


def no_installation() -> str:
    return ui.page("ParaCheck", ui.section("No installation selected", """
        <div class="card"><div class="empty">
          <p style="margin-top:0">This page needs to know which installation to show.</p>
          <p class="small" style="margin-bottom:0">Open it from the link GitHub sent you
          after installing, or <a href="/install">install ParaCheck</a> first.</p>
        </div></div>"""), nav='<a class="btn" href="/install">Add to GitHub</a>')


def unknown_installation() -> str:
    return ui.page("ParaCheck", ui.section("Unknown installation", """
        <div class="card"><div class="empty">
          <p style="margin-top:0">This deployment has no record of that installation.</p>
          <p class="small" style="margin-bottom:0">If you just installed the app,
          <a href="/install">try again</a> - the setup callback may not have completed.</p>
        </div></div>"""), nav='<a class="btn" href="/install">Add to GitHub</a>')


def not_your_installation() -> str:
    """Deliberately does not say whether that installation exists - the id is
    guessable, and confirming one would be its own small leak."""
    return ui.page("ParaCheck", ui.section("Not signed in for this installation", """
        <div class="card"><div class="empty">
          <p style="margin-top:0">This browser hasn't been shown to have access to that
          installation.</p>
          <p class="small" style="margin-bottom:0">Open the dashboard from GitHub -
          <a href="https://github.com/settings/installations">your installations</a> -
          and follow the app's link, or <a href="/install">install ParaCheck</a>.</p>
        </div></div>"""), nav='<a class="btn" href="/install">Add to GitHub</a>')


def billing_unconfigured() -> str:
    return ui.page("ParaCheck", ui.section("Subscriptions aren't enabled here", """
        <div class="card card-pad">
          <p style="margin-top:0">This deployment is running in trial-only mode, so there
          is nothing to upgrade to.</p>
          <p class="muted small" style="margin-bottom:0">Whoever runs it can enable
          subscriptions by setting <code>STRIPE_SECRET_KEY</code> and
          <code>STRIPE_PRICE_ID</code>.</p>
        </div>"""))


def installation_page(
    installation: dict,
    installation_id: int,
    repos: list[str],
    reviews: list[dict],
    queue: dict,
    settings: dict,
    csrf: str = "",
    notice: tuple[str, str] | None = None,
) -> str:
    plan = installation["plan"]
    upgrade = (
        f'<a class="btn" href="/billing/upgrade?installation_id={ui.esc(installation_id)}">Upgrade</a>'
        if plan == "trial" and settings["billing"] else ""
    )
    body = "".join([
        _header(installation, installation_id),
        _summary(repos, reviews, queue),
        _api_key(installation, installation_id, settings, csrf, notice),
        _repositories(repos, reviews, installation_id),
        _history(reviews),
        _deployment(settings),
    ])
    return ui.page(
        f"ParaCheck - {installation['account_login']}",
        body,
        nav=f'<a href="https://github.com/settings/installations/{ui.esc(installation_id)}">'
            f'Manage access</a>{upgrade}',
    )


def _api_key(installation: dict, installation_id: int, settings: dict,
             csrf: str, notice) -> str:
    """Where an installation supplies its own Anthropic key.

    Written to be read by someone deciding whether to paste a live billing
    credential into a web form, so it says plainly what happens to it.
    """
    if not settings["byok"]:
        return ""

    banner = ""
    if notice:
        tone, message = notice
        colour = "var(--good)" if tone == "ok" else "var(--accent)"
        banner = (f'<div class="card card-pad" style="margin-bottom:14px;border-color:{colour}">'
                  f'{ui.esc(message)}</div>')

    hint = installation["anthropic_key_hint"]
    if hint:
        state = f'<span class="chip good">Key installed &middot; <code>{ui.esc(hint)}</code></span>'
        action = ("Replace it by pasting a new one, or remove it to go back to plain "
                  "rendered reviews.")
        remove = (f'<button class="btn ghost" name="action" value="remove" type="submit">'
                  f'Remove key</button>')
    else:
        state = '<span class="chip">No key &middot; reviews are rendered from findings</span>'
        action = ("Add one and reviews get a written summary that prioritises the findings "
                  "instead of listing them.")
        remove = ""

    return ui.section("Claude API key", f"""
      {banner}
      <div class="card card-pad">
        <p style="margin-top:0">{state}</p>
        <p class="muted small">{ui.esc(action)}</p>
        <form method="post" action="/settings/api-key" style="display:flex;gap:10px;flex-wrap:wrap;margin-top:6px">
          <input type="hidden" name="installation_id" value="{ui.esc(installation_id)}">
          <input type="hidden" name="csrf" value="{ui.esc(csrf)}">
          <input type="password" name="api_key" placeholder="sk-ant-..." autocomplete="off"
                 spellcheck="false"
                 style="flex:1;min-width:260px;padding:10px 12px;border:1px solid var(--rule);
                        border-radius:5px;background:var(--bg);color:var(--ink);
                        font-family:'IBM Plex Mono',monospace;font-size:13px">
          <button class="btn" name="action" value="save" type="submit">Save key</button>
          {remove}
        </form>
        <p class="muted small" style="margin-bottom:0;margin-top:14px">
          The key is checked against the Anthropic API before it is stored, encrypted at
          rest with a secret that isn't in the database, and never written to a log or
          passed to the build tools that run your repository's code. Usage is billed to
          your own Anthropic account. Reviews keep working without one - they just arrive
          without the written summary.
        </p>
      </div>""")


def _header(installation: dict, installation_id: int) -> str:
    plan = installation["plan"]
    if plan == "trial":
        left = installation["trial_reviews"]
        status = (f'<span class="chip {"warn" if left <= 5 else "good"}">'
                  f'Trial &middot; {ui.esc(left)} reviews left</span>')
    else:
        status = f'<span class="chip good">{ui.esc(plan.title())} plan</span>'

    suspended = "" if installation["active"] else \
        '<span class="chip warn">Suspended &middot; reviews are paused</span>'

    return f"""<section style="padding:10px 0 0">
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <h1 style="font-size:clamp(26px,4vw,34px)">{ui.esc(installation['account_login'])}</h1>
        {status}{suspended}
      </div>
      <p class="muted small" style="margin:8px 0 0">
        Installation {ui.esc(installation_id)} &middot;
        {ui.esc(str(installation['account_type']).lower())} account &middot;
        connected {ui.esc(ui.ago(installation['created_at']))}
      </p>
    </section>"""


def _summary(repos: list[str], reviews: list[dict], queue: dict) -> str:
    findings = sum(r["findings"] for r in reviews)
    clean = sum(1 for r in reviews if r["findings"] == 0)
    last = reviews[0]["created_at"] if reviews else None
    waiting = queue.get("pending", 0) + queue.get("running", 0)

    cards = "".join([
        ui.stat("Repositories", len(repos), "watched for pull requests"),
        ui.stat("Reviews run", len(reviews), "most recent shown below" if reviews else "none yet"),
        ui.stat("Findings surfaced", findings,
                f"{clean} of {len(reviews)} came back clean" if reviews else "nothing reviewed yet",
                "accent" if findings else "good"),
        ui.stat("In the queue", waiting,
                f"last review {ui.ago(last)}" if last else "idle",
                "accent" if waiting else ""),
    ])
    return ui.section("At a glance", f'<div class="grid grid-4">{cards}</div>{_parked(queue)}')


def _parked(queue: dict) -> str:
    """A job that gave up means a pull request never got its check. That belongs
    on the dashboard, not only in a log nobody is tailing."""
    failed = queue.get("failed", 0)
    if not failed:
        return ""
    return f"""<div class="card card-pad" style="margin-top:14px;border-color:var(--accent)">
      <strong>{ui.esc(failed)} review(s) gave up after retrying.</strong>
      <span class="muted small">Those pull requests have no check on them. The worker log
      says why - most often a project whose dependencies wouldn't install.</span>
    </div>"""


def _repositories(repos: list[str], reviews: list[dict], installation_id: int) -> str:
    if not repos:
        return ui.section("Repositories", f"""
          <div class="card"><div class="empty">
            <p style="margin-top:0">No repositories connected yet.</p>
            <p class="small">Give ParaCheck access to one, then open a pull request that
            touches a <code>.sol</code> file.</p>
            <p style="margin-bottom:0"><a class="btn"
              href="https://github.com/settings/installations/{ui.esc(installation_id)}"
              >Choose repositories</a></p>
          </div></div>""")

    latest: dict[str, dict] = {}
    for review in reviews:
        latest.setdefault(review["full_name"], review)

    rows = ""
    for repo in repos:
        review = latest.get(repo)
        detail = (
            f'#{ui.esc(review["pr_number"])} &middot; {ui.esc(review["findings"])} finding(s) '
            f'&middot; {ui.esc(ui.ago(review["created_at"]))}'
            if review else '<span class="muted">nothing reviewed yet</span>'
        )
        rows += f"""<tr>
          <td><code>{ui.esc(repo)}</code></td>
          <td class="small muted">{detail}</td>
          <td style="text-align:right"><a href="https://github.com/{ui.esc(repo)}/pulls"
             >Pull requests</a></td>
        </tr>"""
    return ui.section("Repositories", f'<div class="card"><table>{rows}</table></div>')


def _history(reviews: list[dict]) -> str:
    if not reviews:
        return ui.section("Review history", """
          <div class="card"><div class="empty">
            Nothing reviewed yet. The first pull request touching a <code>.sol</code> file
            will appear here.
          </div></div>""")

    rows = ""
    for review in reviews:
        findings = review["findings"]
        chip = ('<span class="chip good">clean</span>' if findings == 0
                else f'<span class="chip accent">{ui.esc(findings)}</span>')
        rows += f"""<tr>
          <td><code>{ui.esc(review['full_name'])}</code></td>
          <td><a href="https://github.com/{ui.esc(review['full_name'])}/pull/{ui.esc(review['pr_number'])}"
             >#{ui.esc(review['pr_number'])}</a></td>
          <td><code class="small muted">{ui.esc((review['head_sha'] or '')[:7])}</code></td>
          <td>{chip}</td>
          <td class="small muted">{ui.esc(review['verdict'] or 'reported')}</td>
          <td class="small muted" style="text-align:right">{ui.esc(ui.ago(review['created_at']))}</td>
        </tr>"""
    return ui.section("Review history", f"""
      <div class="card"><table>
        <tr><th>Repository</th><th>PR</th><th>Commit</th><th>Findings</th><th>Verdict</th>
            <th style="text-align:right">When</th></tr>
        {rows}
      </table></div>""")


def _deployment(settings: dict) -> str:
    """What this deployment is configured to do. Without it, "why did my review
    come back without the written summary" is a question only the logs answer."""
    def flag(on: bool, yes: str, no: str) -> str:
        return (f'<span class="chip good">{ui.esc(yes)}</span>' if on
                else f'<span class="chip">{ui.esc(no)}</span>')

    def row(label: str, value: str) -> str:
        return (f'<li>{ui.esc(label)}<span style="margin-left:auto;text-align:right">'
                f'{value}</span></li>')

    left = "".join([
        row("Target chain", f'<code>{ui.esc(settings["chain"])}</code>'),
        row("Reports findings", f'<code>{ui.esc(settings["min_severity"])}</code> and above'),
        row("Blocks the merge at",
            f'<code>{ui.esc(settings["fail_on"])}</code>' if settings["fail_on"]
            else '<span class="muted">never - report only</span>'),
    ])
    right = "".join([
        row("Review summary", flag(settings["llm"], "written by Claude", "rendered from findings")),
        row("Subscriptions", flag(settings["billing"], "enabled", "trial only")),
        row("Worker", flag(settings["inline_worker"], "in this process", "separate process")),
    ])

    return ui.section("This deployment", f"""
      <div class="card card-pad">
        <div class="grid grid-2">
          <ul class="plain">{left}</ul>
          <ul class="plain">{right}</ul>
        </div>
      </div>""")
