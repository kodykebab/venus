"""ParaCheck CI service: one-click GitHub App install, webhooks, PR reviews.

The install flow is deliberately a single click. `/install` issues a CSRF state
and sends the user to GitHub; GitHub handles login, org/repo selection and the
permission grant in its own UI; it then calls back to `/setup` with both an
installation_id and an OAuth code, because the App has "Request user
authorization (OAuth) during installation" enabled. That callback is where the
user is simultaneously logged in and installed - no separate connect step.
"""
from __future__ import annotations

import asyncio
import os

from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import billing
import jobqueue as job_queue
import store
import worker
from github_auth import (
    ConfigurationError,
    authenticated_user,
    exchange_oauth_code,
    verify_webhook_signature,
)

APP_SLUG = os.environ.get("GITHUB_APP_SLUG", "paracheck-ci")
PUBLIC_URL = os.environ.get("PARACHECK_PUBLIC_URL", "")
MIN_SEVERITY = os.environ.get("PARACHECK_MIN_SEVERITY", "low")
FAIL_ON = os.environ.get("PARACHECK_FAIL_ON") or None
CHAIN = os.environ.get("PARACHECK_CHAIN", "monad")

INLINE_WORKER = os.environ.get("PARACHECK_INLINE_WORKER", "1").lower() in ("1", "true", "yes")


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.init_db()
    job_queue.init_queue()

    stop = asyncio.Event()
    task = asyncio.create_task(worker.worker_loop(stop)) if INLINE_WORKER else None
    try:
        yield
    finally:
        if task is not None:
            # Let the in-flight job finish; whatever is unfinished stays queued.
            stop.set()
            await asyncio.wait_for(asyncio.shield(task), timeout=30)


app = FastAPI(title="ParaCheck CI", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/install")
def install() -> RedirectResponse:
    """The "Add to GitHub" button. Everything after this is GitHub's own UI."""
    state = store.issue_state()
    return RedirectResponse(
        f"https://github.com/apps/{APP_SLUG}/installations/new?state={state}",
        status_code=302,
    )


@app.get("/setup")
async def setup(
    installation_id: int | None = None,
    setup_action: str | None = None,
    code: str | None = None,
    state: str | None = None,
) -> RedirectResponse:
    """GitHub's Setup/Callback URL.

    Validating `state` here is not optional: without it an attacker can trick a
    user into attaching their GitHub installation to the attacker's account.
    """
    if not store.consume_state(state or ""):
        raise HTTPException(status_code=400, detail="Invalid or expired state - start the install again.")

    if installation_id is None:
        raise HTTPException(status_code=400, detail="Missing installation_id.")

    login, account_type = "unknown", "User"
    if code:
        try:
            payload = await exchange_oauth_code(code)
            user_token = payload.get("access_token")
            if user_token:
                user = await authenticated_user(user_token)
                login = user.get("login", login)
                account_type = user.get("type", account_type)
            # The user token is used here and deliberately not persisted - the
            # installation token is what the service needs to do its job.
        except ConfigurationError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception:  # noqa: BLE001 - an OAuth hiccup shouldn't lose the installation
            pass

    store.upsert_installation(installation_id, login, account_type)
    return RedirectResponse(f"/dashboard?installation_id={installation_id}", status_code=302)


@app.post("/webhook")
async def webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str | None = Header(default=None),
) -> JSONResponse:
    body = await request.body()
    if not verify_webhook_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Bad signature")

    payload = await request.json()
    installation_id = (payload.get("installation") or {}).get("id")

    if x_github_event == "installation":
        _handle_installation(payload, installation_id)
    elif x_github_event == "installation_repositories":
        _handle_installation_repositories(payload, installation_id)
    elif x_github_event == "pull_request":
        _handle_pull_request(payload, installation_id)

    # Always acknowledge quickly; the work is queued and survives a restart.
    return JSONResponse({"ok": True})


def _handle_installation(payload: dict, installation_id: int | None) -> None:
    action = payload.get("action")
    if installation_id is None:
        return
    account = (payload.get("installation") or {}).get("account") or {}

    if action in ("created", "unsuspend", "new_permissions_accepted"):
        store.upsert_installation(installation_id, account.get("login", "unknown"), account.get("type", "User"))
        store.set_repositories(
            installation_id, [r["full_name"] for r in payload.get("repositories", [])]
        )
    elif action in ("deleted", "suspend"):
        store.deactivate_installation(installation_id)


def _handle_installation_repositories(payload: dict, installation_id: int | None) -> None:
    if installation_id is None:
        return
    store.set_repositories(
        installation_id, [r["full_name"] for r in payload.get("repositories_added", [])]
    )
    store.remove_repositories(
        installation_id, [r["full_name"] for r in payload.get("repositories_removed", [])]
    )


def _handle_pull_request(payload: dict, installation_id: int | None) -> None:
    if payload.get("action") not in ("opened", "synchronize", "reopened"):
        return
    if installation_id is None:
        return

    repository = payload.get("repository") or {}
    pull_request = payload.get("pull_request") or {}
    full_name = repository.get("full_name")
    pr_number = pull_request.get("number")
    head_sha = (pull_request.get("head") or {}).get("sha")
    if not (full_name and pr_number and head_sha):
        return

    # Keyed on the PR, not the commit: three pushes in a row should review the
    # newest head once, not queue three reviews of commits nobody is waiting on.
    job_queue.enqueue(
        "review_pull_request",
        {
            "installation_id": installation_id,
            "full_name": full_name,
            "pr_number": pr_number,
            "head_sha": head_sha,
            "min_severity": MIN_SEVERITY,
            "fail_on": FAIL_ON,
            "chain": CHAIN,
        },
        dedupe_key=f"review:{full_name}#{pr_number}",
    )


@app.get("/billing/upgrade")
async def billing_upgrade(installation_id: int, request: Request):
    """Sends the user to Stripe Checkout. Only reachable after install - the
    trial is what keeps signup itself card-free."""
    base = PUBLIC_URL or str(request.base_url).rstrip("/")
    url = await billing.create_checkout_session(
        installation_id,
        success_url=f"{base}/dashboard?installation_id={installation_id}",
        cancel_url=f"{base}/dashboard?installation_id={installation_id}",
    )
    if url is None:
        return HTMLResponse(
            _page("<h1>Billing isn't configured</h1><p>This deployment is running in "
                  "trial-only mode. Set STRIPE_SECRET_KEY and STRIPE_PRICE_ID to enable "
                  "subscriptions.</p>"),
            status_code=503,
        )
    return RedirectResponse(url, status_code=302)


@app.post("/billing/webhook")
async def billing_webhook(request: Request, stripe_signature: str = Header(default="")) -> JSONResponse:
    body = await request.body()
    if not billing.verify_webhook_signature(body, stripe_signature):
        raise HTTPException(status_code=401, detail="Bad signature")

    outcome = billing.apply_event(await request.json())
    if outcome:
        print(f"paracheck: {outcome}")
    return JSONResponse({"ok": True})


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(installation_id: int | None = None) -> HTMLResponse:
    if installation_id is None:
        return HTMLResponse(_page("<p>No installation selected.</p>"))

    installation = store.get_installation(installation_id)
    if installation is None:
        return HTMLResponse(_page("<p>Unknown installation.</p>"), status_code=404)

    repos = store.active_repositories(installation_id)
    reviews = store.recent_reviews(installation_id, 20)

    plan = installation["plan"]
    if plan == "trial":
        quota = f"Trial — {installation['trial_reviews']} reviews left"
        upgrade = (
            f'<p><a href="/billing/upgrade?installation_id={installation_id}">Upgrade</a></p>'
            if billing.configured()
            else '<p><em>Billing isn\'t configured on this deployment — trial only.</em></p>'
        )
    else:
        quota = f"Plan: {plan}"
        upgrade = ""

    repo_rows = "".join(f"<li><code>{r}</code></li>" for r in repos) or "<li>No repositories yet.</li>"
    review_rows = "".join(
        f"<tr><td><code>{r['full_name']}</code></td><td>#{r['pr_number']}</td>"
        f"<td>{r['verdict'] or '-'}</td><td>{r['findings']}</td></tr>"
        for r in reviews
    ) or "<tr><td colspan=4>No reviews yet - open a pull request.</td></tr>"

    return HTMLResponse(_page(f"""
      <h1>ParaCheck</h1>
      <p><strong>{installation['account_login']}</strong> — {quota}</p>
      {upgrade}
      <h2>Connected repositories</h2>
      <ul>{repo_rows}</ul>
      <h2>Recent reviews</h2>
      <table><tr><th>Repository</th><th>PR</th><th>Verdict</th><th>Findings</th></tr>{review_rows}</table>
    """))


def _page(body: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>ParaCheck</title><style>
body{{font-family:'IBM Plex Sans',-apple-system,sans-serif;max-width:760px;margin:0 auto;padding:40px 20px;
background:#faf9f7;color:#14130f}}
h1{{font-size:28px;letter-spacing:-.02em}} h2{{font-size:16px;margin-top:32px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{text-align:left;padding:8px;border-bottom:1px solid #ddd9cf}}
code{{background:#f1efe8;padding:2px 6px;border-radius:3px;font-size:13px}}
</style></head><body>{body}</body></html>"""
