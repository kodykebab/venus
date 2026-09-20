"""The pages a human looks at: marketing, pricing, checkout and the dashboard.

Kept out of app.py so the routes stay readable - app.py should show what the
service does, not how a table gets rendered.

Copy follows style.md: concrete, outcome-oriented, never accusatory. A finding
is an optimisation opportunity, not a mistake the developer made. Numbers are
only ever stated when something actually measured them.

Plan names, prices and quotas are read from billing.PLANS rather than written
here, so the pricing page cannot drift from what the gate enforces.
"""
from __future__ import annotations

import urllib.parse

import billing
import ui

# --- shared chrome ----------------------------------------------------------

NAV_PUBLIC = (
    '<a href="/#how">How it works</a>'
    '<a href="/pricing">Pricing</a>'
    '<a class="btn small" href="/install">Connect GitHub</a>'
)


def _enterprise_mailto(sales_email: str) -> str:
    """A prefilled message, because "email us" with an empty compose window is
    where most enterprise enquiries quietly die."""
    subject = "ParaCheck Enterprise enquiry"
    body = (
        "Hi ParaCheck team,\n\n"
        "We're looking at ParaCheck for our contracts.\n\n"
        "Company:\n"
        "Repositories to cover:\n"
        "Chains we ship to:\n"
        "Approximate pull requests per week:\n"
        "What we need (quota, deployment, support):\n\n"
        "Thanks,\n"
    )
    query = urllib.parse.urlencode({"subject": subject, "body": body}, quote_via=urllib.parse.quote)
    return f"mailto:{sales_email}?{query}"


# --- marketing --------------------------------------------------------------

def landing(chain: str) -> str:
    """style.md 5-6: the hero shows the product doing something, next to one
    obvious action. Whoever follows a teammate's link has never heard of this."""
    hero = f"""
    <section class="section" style="margin-top:8px">
      <div class="hero">
        <div class="hero-copy">
          <h1>Ship cheaper contracts.</h1>
          <p class="lede" style="margin-top:20px">
            ParaCheck finds the storage, execution and parallelism patterns making your
            Solidity expensive &mdash; and shows you exactly what to change.
          </p>
          <div class="btn-row" style="margin-top:28px">
            <a class="btn" href="/install">Connect GitHub</a>
            <a class="btn secondary" href="#how">See how it works</a>
          </div>
          <p class="small dim" style="margin-top:16px">
            Reviews run on every pull request. Currently analysing for
            <code class="inline">{ui.esc(chain)}</code>.
          </p>
        </div>
        {_hero_proof()}
      </div>
    </section>"""

    return ui.page(
        "ParaCheck - ship cheaper contracts",
        hero + _problem() + _how_it_works() + _workflow() + _credibility() + _closing_cta(),
        nav=NAV_PUBLIC,
        description=("ParaCheck finds the storage, execution and parallelism patterns "
                     "making your Solidity expensive, and shows you what to change."),
    )


def _hero_proof() -> str:
    """A slice of the real report surface, labelled as a sample. style.md 41:
    never imply demo output came from the visitor's code."""
    findings = [
        ("critical", "Critical", "swap()", "Storage contention",
         "reserve0, reserve1 and totalLiquidity are written on every swap, so concurrent "
         "swaps serialise."),
        ("warn", "High", "deposit()", "Repeated storage read",
         "balance[user] is loaded four times in one path."),
        ("accent", "Medium", "claim()", "Write with no state change",
         "lastClaim is rewritten even when the value is unchanged."),
    ]
    rows = ""
    for tone, label, fn, title, body in findings:
        rows += f"""
      <div class="finding">
        <div class="finding-head">
          {ui.badge(label, tone)}
          <code class="fn">{ui.esc(fn)}</code>
        </div>
        <div class="finding-title">{ui.esc(title)}</div>
        <p class="finding-body">{ui.esc(body)}</p>
      </div>"""

    return f"""
    <div class="panel proof" aria-label="Sample ParaCheck report">
      <div class="proof-head">
        <code class="mono">NaiveAMM.sol</code>
        <span class="badge">Sample report</span>
      </div>
      <div class="proof-summary">
        <div>
          <div class="stat-label">Optimisation opportunities</div>
          <div class="stat-value">3</div>
        </div>
        <div>
          <div class="stat-label">Contended slots</div>
          <div class="stat-value is-critical">2</div>
        </div>
      </div>
      {rows}
    </div>
    <style>
      .hero {{ display: grid; grid-template-columns: 5fr 7fr; gap: 56px; align-items: start; }}
      @media (max-width: 960px) {{ .hero {{ grid-template-columns: 1fr; gap: 40px; }} }}
      .proof {{ overflow: hidden; }}
      .proof-head {{
        display: flex; align-items: center; gap: 12px;
        padding: 14px 20px; border-bottom: 1px solid var(--line);
        background: var(--surface-2);
      }}
      .proof-head .badge {{ margin-left: auto; }}
      .proof-summary {{
        display: grid; grid-template-columns: 1fr 1fr; gap: 20px;
        padding: 20px; border-bottom: 1px solid var(--line);
      }}
      .proof-summary .stat-value {{ font-size: 34px; }}
      .finding {{ padding: 18px 20px; border-bottom: 1px solid var(--line); }}
      .finding:last-child {{ border-bottom: none; }}
      .finding-head {{ display: flex; align-items: center; gap: 10px; }}
      .finding-head .fn {{ color: var(--ink-2); }}
      .finding-title {{ font-weight: 600; margin-top: 10px; font-size: 15px; }}
      .finding-body {{ color: var(--ink-2); font-size: 14px; margin-top: 4px; }}
    </style>"""


def _problem() -> str:
    return ui.section("The problem", """
      <div class="grid grid-2" style="gap:56px">
        <p class="lede">
          On a chain that executes transactions in parallel, two transactions touching the
          same storage slot cannot run at the same time. One is thrown away and re-executed.
        </p>
        <p class="lede">
          That cost is decided when the contract is written, and it is invisible in a normal
          diff. Nothing in a standard review tells you which slots will contend.
        </p>
      </div>""")


def _how_it_works() -> str:
    stages = [
        ("Static", "Slither's detector suite plus ParaCheck's hot-slot classifier, "
                   "mapping which functions touch which storage."),
        ("Dynamic", "Foundry and anvil run the contract under concurrent load and the "
                    "execution traces are diffed for real conflicts."),
        ("Report", "Findings are prioritised by measured impact and posted to the pull "
                   "request as a Check Run with inline annotations."),
    ]
    cards = "".join(f"""
      <div>
        <div class="stat-label">{ui.esc(name)}</div>
        <p class="muted" style="font-size:14px;margin-top:8px">{ui.esc(body)}</p>
      </div>""" for name, body in stages)
    return f"""<section class="section" id="how">
      <h2 class="eyebrow">How ParaCheck finds it</h2>
      <div class="grid grid-3" style="gap:40px">{cards}</div>
    </section>"""


def _workflow() -> str:
    return ui.section("In your pull requests", """
      <div class="panel panel-pad">
        <ul class="rows">
          <li><code class="inline">1</code> Install the app on the repositories you choose.</li>
          <li><code class="inline">2</code> Open a pull request that touches a <code class="inline">.sol</code> file.</li>
          <li><code class="inline">3</code> ParaCheck checks the branch out, installs its dependencies, compiles and analyses it.</li>
          <li><code class="inline">4</code> A Check Run appears with annotations on the lines involved &mdash; and can gate the merge.</li>
        </ul>
      </div>""")


def _credibility() -> str:
    rows = [
        ("Static analysis", "Slither + hot-slot classifier"),
        ("Dynamic analysis", "Foundry / anvil execution traces"),
        ("Execution", "GitHub Actions"),
        ("Integration", "Native PR Check Runs and annotations"),
    ]
    items = "".join(
        f'<li>{ui.esc(k)}<span class="spacer muted">{ui.esc(v)}</span></li>' for k, v in rows
    )
    return ui.section("What it is built on", f"""
      <div class="panel panel-pad"><ul class="rows">{items}</ul></div>
      <p class="small dim" style="margin-top:14px">
        Analysis runs in GitHub Actions, where the repository's own build system executes.
        The hosted control plane never compiles your code.
      </p>""")


def _closing_cta() -> str:
    return f"""<section class="section">
      <div class="panel panel-pad" style="display:flex;gap:24px;align-items:center;flex-wrap:wrap">
        <div>
          <h3>Put ParaCheck in your pull requests.</h3>
          <p class="muted" style="font-size:14px;margin-top:6px">
            One install. No configuration file, no YAML, no compiler settings.
          </p>
        </div>
        <div class="btn-row" style="margin-left:auto">
          <a class="btn" href="/install">Connect GitHub</a>
          <a class="btn secondary" href="/pricing">See pricing</a>
        </div>
      </div>
    </section>"""


# --- pricing ----------------------------------------------------------------

def pricing_page(sales_email: str, installation_id: int | None = None) -> str:
    """style.md 34: simple, no fake discounts, quotas stated plainly. Every
    number here comes from billing.PLANS."""
    suffix = f"?installation_id={installation_id}" if installation_id else ""

    def card(key: str, details: dict, action: str, featured: bool = False) -> str:
        features = "".join(
            f'<li>{ui.esc(f)}</li>' for f in details["features"]
        )
        return f"""
        <div class="panel panel-pad plan{' is-featured' if featured else ''}">
          <div class="stat-label">{ui.esc(details['label'])}</div>
          <div class="plan-price">
            {ui.esc(details['price'])}<span class="plan-cadence">{ui.esc(details['cadence'])}</span>
          </div>
          <p class="muted small" style="margin-top:8px">{ui.esc(details['blurb'])}</p>
          <ul class="plan-features">{features}</ul>
          <div class="btn-row" style="margin-top:auto;padding-top:20px">{action}</div>
        </div>"""

    hobby = billing.plan_details("hobby")
    pro = billing.plan_details("pro")

    hobby_action = f'<a class="btn secondary" href="/account{suffix or "?"}{"&" if suffix else ""}plan=hobby">Choose Hobby</a>'
    pro_action = f'<a class="btn" href="/account{suffix or "?"}{"&" if suffix else ""}plan=pro">Choose Pro</a>'
    if not installation_id:
        # Without an installation there is nothing to bill, so the honest first
        # step is connecting GitHub rather than a checkout that would 400.
        hobby_action = '<a class="btn secondary" href="/install">Connect GitHub</a>'
        pro_action = '<a class="btn" href="/install">Connect GitHub</a>'

    enterprise_action = (
        f'<a class="btn secondary" href="{ui.esc(_enterprise_mailto(sales_email))}">Talk to us</a>'
        if sales_email else
        '<span class="small dim">Enterprise contact is not configured on this deployment.</span>'
    )

    body = f"""
    <section class="section" style="margin-top:8px">
      <h1 style="font-size:clamp(32px,4.4vw,52px)">Pricing</h1>
      <p class="lede" style="margin-top:16px">
        A scan compiles and analyses a repository, so plans are capped by scans per week
        rather than sold as unlimited. Quota is counted over a rolling seven days.
      </p>
    </section>

    <section class="section" style="margin-top:48px">
      <div class="grid grid-3 plans">
        {card("hobby", hobby, hobby_action)}
        {card("pro", pro, pro_action, featured=True)}
        {card("enterprise", billing.ENTERPRISE, enterprise_action)}
      </div>
      <p class="small dim" style="margin-top:20px">
        A scan is one analysis of one pull request. Pushing again to an open pull request
        replaces the queued scan rather than spending another one.
      </p>
    </section>

    <style>
      .plans {{ align-items: stretch; }}
      .plan {{ display: flex; flex-direction: column; }}
      .plan.is-featured {{ border-color: var(--accent); }}
      .plan-price {{
        font-size: 40px; font-weight: 600; letter-spacing: -0.035em;
        margin-top: 10px; font-variant-numeric: tabular-nums;
      }}
      .plan-cadence {{ font-size: 15px; font-weight: 400; color: var(--ink-3); letter-spacing: 0; }}
      .plan-features {{
        list-style: none; padding: 0; margin: 20px 0 0;
        font-size: 14px; color: var(--ink-2);
      }}
      .plan-features li {{ padding: 7px 0; border-bottom: 1px solid var(--line); }}
      .plan-features li:last-child {{ border-bottom: none; }}
    </style>"""

    return ui.page("ParaCheck - pricing", body, nav=NAV_PUBLIC,
                   description="ParaCheck pricing: Hobby $9/month for 20 scans a week, "
                               "Pro $29/month for 100, Enterprise custom.")


def enterprise_page(sales_email: str) -> str:
    """Sales-led, so this page's only job is to open a prefilled message."""
    if not sales_email:
        return ui.page("ParaCheck - Enterprise", ui.section("Enterprise", ui.empty_state(
            "Enterprise contact isn't configured",
            "This deployment has no sales address set, so there is nowhere to send an "
            "enquiry. Whoever runs it can set ENTERPRISE_SALES_EMAIL.",
        ), first=True), nav=NAV_PUBLIC)

    features = "".join(f"<li>{ui.esc(f)}</li>" for f in billing.ENTERPRISE["features"])
    body = f"""
    <section class="section" style="margin-top:8px">
      <h1 style="font-size:clamp(32px,4.4vw,52px);max-width:16ch">Let's talk.</h1>
      <p class="lede" style="margin-top:16px">
        Tell us the repositories you want covered, the chains you ship to and roughly how
        many pull requests a week. We'll design a capped plan around it and send a quote.
      </p>
      <div class="btn-row" style="margin-top:28px">
        <a class="btn" href="{ui.esc(_enterprise_mailto(sales_email))}">Email us</a>
        <a class="btn secondary" href="/pricing">Compare plans</a>
      </div>
      <p class="small dim" style="margin-top:14px">
        Opens your mail client with the details we need already filled in. Goes to
        <code class="inline">{ui.esc(sales_email)}</code>.
      </p>
    </section>

    <section class="section">
      <h2 class="eyebrow">What Enterprise includes</h2>
      <div class="panel panel-pad">
        <ul class="rows">{features}</ul>
      </div>
    </section>"""
    return ui.page("ParaCheck - Enterprise", body, nav=NAV_PUBLIC)


# --- account / checkout -----------------------------------------------------

def account_page(installation_id: int, publishable_key: str, plan: str = "pro") -> str:
    """A deliberately small Clerk shell: identity in the browser, payment in
    Stripe. Plan labels are read from billing so they cannot go stale."""
    options = "".join(
        f'<option value="{ui.esc(key)}"{" selected" if key == plan else ""}>'
        f'{ui.esc(d["label"])} &mdash; {ui.esc(d["price"])}{ui.esc(d["cadence"])}, '
        f'{ui.esc(d["review_limit"])} scans per week</option>'
        for key, d in ((k, billing.plan_details(k)) for k in billing.PLANS)
    )

    body = f"""
    <section class="section" style="margin-top:8px">
      <h1 style="font-size:clamp(30px,4vw,44px);max-width:18ch">Start reviewing pull requests.</h1>
      <p class="lede" style="margin-top:16px">
        Sign in, then continue to Stripe Checkout. Stripe handles the card; ParaCheck never
        sees it.
      </p>
    </section>

    <section class="section" style="margin-top:40px">
      <div class="panel panel-pad" style="max-width:520px">
        <p id="clerk-status" class="small muted" aria-live="polite">Loading secure sign-in&hellip;</p>
        <label class="label" for="plan">Plan</label>
        <select id="plan" class="field">{options}</select>
        <div class="btn-row" style="margin-top:18px">
          <button id="checkout" class="btn" type="button" disabled>Continue to checkout</button>
        </div>
        <p class="small dim" style="margin-top:16px">
          Quota is counted over a rolling seven days, so it frees up continuously rather
          than resetting on one day of the month.
        </p>
        <p class="small" style="margin-top:10px">
          <a href="/enterprise">Need a custom quota? Talk to us about Enterprise.</a>
        </p>
      </div>
    </section>

    <script defer crossorigin="anonymous" src="https://cdn.jsdelivr.net/npm/@clerk/clerk-js@5/dist/clerk.browser.js"></script>
    <script>
      const installationId = {ui.esc(installation_id)};
      const publishableKey = {ui.esc(publishable_key)!r};
      const planSelect = document.getElementById("plan");
      const status = document.getElementById("clerk-status");
      const checkout = document.getElementById("checkout");

      async function boot() {{
        if (!publishableKey) {{
          status.textContent = "Sign-in is not configured on this deployment.";
          return;
        }}
        await Clerk.load({{ publishableKey }});
        if (!Clerk.user) {{
          status.textContent = "Sign in to continue.";
          Clerk.openSignIn({{ afterSignInUrl: window.location.href }});
          return;
        }}
        const who = Clerk.user.primaryEmailAddress?.emailAddress || Clerk.user.id;
        status.textContent = "Signed in as " + who;
        checkout.disabled = false;
      }}

      checkout.addEventListener("click", async () => {{
        checkout.disabled = true;
        status.textContent = "Opening secure checkout\\u2026";
        try {{
          const token = await Clerk.session.getToken();
          const response = await fetch("/billing/checkout", {{
            method: "POST",
            headers: {{ "content-type": "application/json", "authorization": "Bearer " + token }},
            body: JSON.stringify({{ installation_id: installationId, plan: planSelect.value }})
          }});
          const data = await response.json();
          if (!response.ok) throw new Error(data.detail || "Checkout is unavailable right now.");
          window.location.href = data.url;
        }} catch (error) {{
          status.textContent = error.message;
          checkout.disabled = false;
        }}
      }});

      window.addEventListener("load", () => boot().catch(error => {{
        status.textContent = error.message;
      }}));
    </script>"""
    return ui.page("ParaCheck - checkout", body, nav=NAV_PUBLIC)


# --- states -----------------------------------------------------------------

def no_installation() -> str:
    return ui.page("ParaCheck", ui.section("Dashboard", ui.empty_state(
        "No installation selected",
        "This page needs to know which installation to show. Open it from the link GitHub "
        "sent you after installing.",
        '<a class="btn" href="/install">Connect GitHub</a>',
    ), first=True), nav=NAV_PUBLIC)


def unknown_installation() -> str:
    return ui.page("ParaCheck", ui.section("Dashboard", ui.empty_state(
        "Unknown installation",
        "This deployment has no record of that installation. If you just installed the app, "
        "the setup callback may not have completed.",
        '<a class="btn" href="/install">Try installing again</a>',
    ), first=True), nav=NAV_PUBLIC)


def not_your_installation() -> str:
    """Renders identically whether or not the installation exists - the id is
    guessable, and confirming one would be its own small leak."""
    return ui.page("ParaCheck", ui.section("Dashboard", ui.empty_state(
        "Not signed in for this installation",
        "This browser hasn't been shown to have access to that installation. Open the "
        "dashboard from the link GitHub gave you after installing.",
        '<a class="btn" href="/install">Connect GitHub</a>',
    ), first=True), nav=NAV_PUBLIC)


def billing_unconfigured() -> str:
    return ui.page("ParaCheck", ui.section("Checkout", ui.empty_state(
        "Checkout isn't available here",
        "This deployment has no Stripe configuration, so there is nothing to subscribe to. "
        "Whoever runs it can set STRIPE_SECRET_KEY and the plan price IDs.",
        '<a class="btn secondary" href="/pricing">See pricing</a>',
    ), first=True), nav=NAV_PUBLIC)


# --- dashboard --------------------------------------------------------------

def installation_page(
    installation: dict,
    installation_id: int,
    repos: list[str],
    reviews: list[dict],
    queue: dict,
    settings: dict,
    quota: dict,
    scans: dict | None = None,
    csrf: str = "",
    notice: tuple[str, str] | None = None,
) -> str:
    nav = (f'<a href="/pricing">Pricing</a>'
           f'<a href="https://github.com/settings/installations/{ui.esc(installation_id)}">Manage access</a>')
    if quota["plan"] not in billing.PLANS and quota["plan"] != "enterprise":
        nav += f'<a class="btn small" href="/account?installation_id={ui.esc(installation_id)}">Choose a plan</a>'

    body = "".join([
        _notice(notice),
        _header(installation, installation_id, quota),
        _summary(repos, reviews, queue, quota),
        _plan_gate(installation_id, quota),
        _api_key(installation, installation_id, settings, csrf),
        _repositories(repos, reviews, installation_id, scans or {}, quota, csrf),
        _history(reviews),
        _deployment(settings),
    ])
    return ui.page(f"ParaCheck - {installation['account_login']}", body, nav=nav)


def _notice(notice: tuple[str, str] | None) -> str:
    if not notice:
        return ""
    tone, message = notice
    css = "is-ok" if tone == "ok" else "is-error"
    return f'<div class="notice {css}" role="status" style="margin-bottom:24px">{ui.esc(message)}</div>'


def _header(installation: dict, installation_id: int, quota: dict) -> str:
    plan = quota["plan"]
    details = billing.plan_details(plan)
    if details and quota["limit"] is None:
        status = ui.badge(f"{details['label']} plan", "ok")
    elif details:
        remaining = quota["remaining"]
        tone = "ok" if remaining > 3 else ("warn" if remaining else "critical")
        status = ui.badge(f"{details['label']} · {remaining} of {quota['limit']} scans left", tone)
    else:
        status = ui.badge("No plan", "warn")

    suspended = "" if installation["active"] else ui.badge("Suspended", "critical")

    return f"""<section class="section" style="margin-top:0">
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <h1 style="font-size:clamp(26px,3.4vw,36px)">{ui.esc(installation['account_login'])}</h1>
        {status}{suspended}
      </div>
      <p class="small dim" style="margin-top:10px">
        Installation {ui.esc(installation_id)} &middot;
        {ui.esc(str(installation['account_type']).lower())} account &middot;
        connected {ui.esc(ui.ago(installation['created_at']))}
      </p>
    </section>"""


def _summary(repos: list[str], reviews: list[dict], queue: dict, quota: dict) -> str:
    findings = sum(r["findings"] for r in reviews)
    clean = sum(1 for r in reviews if r["findings"] == 0)
    waiting = queue.get("pending", 0) + queue.get("running", 0)

    if quota["limit"] is None:
        quota_value, quota_note = quota["used"], "this week · no fixed cap"
    else:
        quota_value = f"{quota['used']}/{quota['limit']}"
        quota_note = "used in the last 7 days"
        if quota["remaining"] == 0 and quota["resets_at"]:
            quota_note = f"quota frees up in {ui.until(quota['resets_at'])}"

    cards = "".join([
        ui.stat("Repositories", len(repos), "watched for pull requests"),
        ui.stat("Scans this week", quota_value, quota_note,
                "critical" if quota["limit"] is not None and quota["remaining"] == 0 else ""),
        ui.stat("Opportunities found", findings,
                f"{clean} of {len(reviews)} came back clean" if reviews else "nothing analysed yet",
                "accent" if findings else ""),
        ui.stat("In the queue", waiting, "idle" if not waiting else "running now",
                "accent" if waiting else ""),
    ])
    return ui.section("At a glance", f'<div class="grid grid-4">{cards}</div>{_parked(queue)}')


def _parked(queue: dict) -> str:
    """A job that gave up means a pull request never got its check. That belongs
    on the dashboard, not only in a log nobody is tailing."""
    failed = queue.get("failed", 0)
    if not failed:
        return ""
    return f"""<div class="notice is-error" style="margin-top:16px">
      <strong>{ui.esc(failed)} scan(s) stopped after retrying.</strong>
      <span class="muted">Those pull requests have no check on them. The worker log says
      why &mdash; most often a project whose dependencies wouldn't install.</span>
    </div>"""


def _plan_gate(installation_id: int, quota: dict) -> str:
    """The dominant action when an account can't actually run anything."""
    plan = quota["plan"]
    if plan in billing.PLANS or plan == "enterprise":
        return ""
    hobby, pro = billing.plan_details("hobby"), billing.plan_details("pro")
    return ui.section("Choose a plan", f"""
      <div class="panel panel-pad" style="display:flex;gap:24px;align-items:center;flex-wrap:wrap">
        <div>
          <h3>Pull requests aren't being scanned yet.</h3>
          <p class="muted" style="font-size:14px;margin-top:6px;max-width:56ch">
            {ui.esc(hobby['label'])} is {ui.esc(hobby['price'])}{ui.esc(hobby['cadence'])} for
            {ui.esc(hobby['review_limit'])} scans a week, {ui.esc(pro['label'])} is
            {ui.esc(pro['price'])}{ui.esc(pro['cadence'])} for {ui.esc(pro['review_limit'])}.
          </p>
        </div>
        <div class="btn-row" style="margin-left:auto">
          <a class="btn" href="/account?installation_id={ui.esc(installation_id)}">Choose a plan</a>
          <a class="btn secondary" href="/pricing">Compare</a>
        </div>
      </div>""")


def _api_key(installation: dict, installation_id: int, settings: dict, csrf: str) -> str:
    """Bring-your-own Claude key. Only rendered when the deployment has the
    feature switched on - otherwise it advertises something that does nothing."""
    if not settings.get("byok") or not settings.get("claude_enabled"):
        return ""

    hint = installation["anthropic_key_hint"]
    if hint:
        state = ui.badge(f"Key installed · {hint}", "ok")
        blurb = "Replace it by pasting a new one, or remove it to go back to plain findings."
        remove = ('<button class="btn secondary" name="action" value="remove" type="submit">'
                  'Remove key</button>')
        getting = ""
    else:
        state = ui.badge("No key", "")
        blurb = ("Findings are deterministic either way. A key adds a written summary that "
                 "prioritises them.")
        remove = ""
        getting = """
        <p class="small dim" style="margin-top:12px">
          Create one in <a href="https://console.anthropic.com/settings/keys" target="_blank"
          rel="noopener noreferrer">the Anthropic console</a>. API billing is separate from a
          Claude.ai subscription, which doesn't include API access.
        </p>"""

    return ui.section("Claude API key (optional)", f"""
      <div class="panel panel-pad">
        <p>{state}</p>
        <p class="muted small" style="margin-top:10px">{ui.esc(blurb)}</p>
        {getting}
        <form method="post" action="/settings/api-key" class="btn-row" style="margin-top:16px">
          <input type="hidden" name="installation_id" value="{ui.esc(installation_id)}">
          <input type="hidden" name="csrf" value="{ui.esc(csrf)}">
          <label class="label" for="api_key" style="position:absolute;left:-9999px">Anthropic API key</label>
          <input class="field mono" id="api_key" type="password" name="api_key"
                 placeholder="sk-ant-..." autocomplete="off" spellcheck="false"
                 style="flex:1;min-width:240px">
          <button class="btn" name="action" value="save" type="submit">Save key</button>
          {remove}
        </form>
        <p class="small dim" style="margin-top:14px;margin-bottom:0">
          Checked against the API before it is stored, encrypted at rest, never logged, and
          never placed in the environment your repository's build tools inherit. Usage is
          billed to your own Anthropic account.
        </p>
      </div>""")


SCAN_STATES = {
    "queued": ("Scanning\u2026", "accent"),
    "done": ("Scanned", "ok"),
    "empty": ("No Solidity", ""),
    "failed": ("Scan failed", "critical"),
    "blocked": ("Not run", "warn"),
}


def _repositories(repos: list[str], reviews: list[dict], installation_id: int,
                  scans: dict, quota: dict, csrf: str) -> str:
    """Each repository carries its own primary action, because the first useful
    thing a new installation can do should not be "wait for someone to open a
    pull request"."""
    if not repos:
        return ui.section("Repositories", ui.empty_state(
            "No repositories connected",
            "Give ParaCheck access to a repository and you can scan it straight away - "
            "no pull request needed.",
            f'<a class="btn" href="https://github.com/settings/installations/'
            f'{ui.esc(installation_id)}">Choose repositories</a>',
        ))

    latest: dict[str, dict] = {}
    for review in reviews:
        latest.setdefault(review["full_name"], review)

    can_scan = quota["limit"] is None or quota["remaining"] > 0

    rows = ""
    for repo in repos:
        scan = scans.get(repo)
        review = latest.get(repo)

        if scan and scan["state"] in SCAN_STATES:
            label, tone = SCAN_STATES[scan["state"]]
            status = (f'{ui.badge(label, tone)} '
                      f'<span class="small dim">{ui.esc(scan["message"] or "")}</span>')
        elif review:
            where = f'#{ui.esc(review["pr_number"])}' if review["pr_number"] else "default branch"
            status = (f'<span class="small muted">{where} &middot; '
                      f'{ui.esc(review["findings"])} '
                      f'opportunit{"y" if review["findings"] == 1 else "ies"} &middot; '
                      f'{ui.esc(ui.ago(review["created_at"]))}</span>')
        else:
            status = '<span class="small dim">not scanned yet</span>'

        scanning = bool(scan and scan["state"] == "queued")
        if scanning:
            action = '<span class="small dim">in progress</span>'
        elif can_scan:
            action = f"""<form method="post" action="/scan" style="display:inline">
              <input type="hidden" name="installation_id" value="{ui.esc(installation_id)}">
              <input type="hidden" name="full_name" value="{ui.esc(repo)}">
              <input type="hidden" name="csrf" value="{ui.esc(csrf)}">
              <button class="btn secondary small" type="submit">Scan now</button>
            </form>"""
        else:
            action = ('<span class="small dim" title="This week\u2019s quota is used up">'
                      'No scans left</span>')

        rows += f"""<tr>
          <td data-label="Repository"><code>{ui.esc(repo)}</code></td>
          <td data-label="Status">{status}</td>
          <td data-label="" style="text-align:right">{action}</td>
        </tr>"""

    hint = ("" if can_scan else
            '<p class="small dim" style="margin-top:12px">Scans resume as this week\u2019s '
            'quota frees up.</p>')
    return ui.section("Repositories", f"""
      <div class="panel"><table class="responsive"><tbody>{rows}</tbody></table></div>
      <p class="small dim" style="margin-top:12px">
        A scan analyses the default branch and posts the result as a check on that commit.
        Pull requests are scanned automatically.
      </p>{hint}""")


def _history(reviews: list[dict]) -> str:
    if not reviews:
        return ui.section("Scan history", ui.empty_state(
            "No scans yet",
            "The first pull request touching a .sol file will appear here, with what it "
            "found and how long it took.",
        ))

    rows = ""
    for review in reviews:
        findings = review["findings"]
        state = (ui.badge("Clean", "ok") if findings == 0
                 else ui.badge(f"{findings} found", "warn"))
        # An on-demand scan has no pull request, so it links the commit instead
        # of rendering a link to /pull/None.
        sha = (review["head_sha"] or "")[:7]
        if review["pr_number"]:
            where = (f'<a href="https://github.com/{ui.esc(review["full_name"])}'
                     f'/pull/{ui.esc(review["pr_number"])}">#{ui.esc(review["pr_number"])}</a>')
        elif sha:
            where = (f'<a href="https://github.com/{ui.esc(review["full_name"])}'
                     f'/commit/{ui.esc(review["head_sha"])}">default branch</a>')
        else:
            where = '<span class="dim">default branch</span>'

        rows += f"""<tr>
          <td data-label="Repository"><code>{ui.esc(review['full_name'])}</code></td>
          <td data-label="Scan of">{where}</td>
          <td data-label="Commit"><code class="small dim">{ui.esc(sha)}</code></td>
          <td data-label="Result">{state}</td>
          <td data-label="Verdict" class="small muted">{ui.esc(review['verdict'] or 'reported')}</td>
          <td data-label="When" class="small dim" style="text-align:right">{ui.esc(ui.ago(review['created_at']))}</td>
        </tr>"""
    return ui.section("Scan history", f"""
      <div class="panel"><table class="responsive">
        <thead><tr><th>Repository</th><th>Scan of</th><th>Commit</th><th>Result</th><th>Verdict</th>
            <th style="text-align:right">When</th></tr></thead>
        <tbody>{rows}</tbody>
      </table></div>""")


def _deployment(settings: dict) -> str:
    """What this deployment is configured to do. Without it, "why did my scan
    behave that way" is a question only the logs can answer."""
    def row(label: str, value: str) -> str:
        return f'<li>{ui.esc(label)}<span class="spacer muted">{value}</span></li>'

    left = "".join([
        row("Target chain", f'<code>{ui.esc(settings["chain"])}</code>'),
        row("Reports findings", f'<code>{ui.esc(settings["min_severity"])}</code> and above'),
        row("Blocks the merge at",
            f'<code>{ui.esc(settings["fail_on"])}</code>' if settings["fail_on"]
            else '<span class="dim">never &mdash; report only</span>'),
    ])
    right = "".join([
        row("Written summaries", "enabled" if settings.get("claude_enabled") else "off — deterministic findings"),
        row("Checkout", "enabled" if settings["billing"] else "not configured"),
        row("Worker", "in this process" if settings["inline_worker"] else "separate process"),
    ])
    return ui.section("This deployment", f"""
      <div class="panel panel-pad">
        <div class="grid grid-2">
          <ul class="rows">{left}</ul>
          <ul class="rows">{right}</ul>
        </div>
      </div>""")
