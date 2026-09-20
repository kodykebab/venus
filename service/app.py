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

from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import billing
import clerk_auth
import dashboard as pages
import jobqueue as job_queue
import secrets_store
import sessions
import store
import ui
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
SALES_EMAIL = os.environ.get("ENTERPRISE_SALES_EMAIL", "")

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
    request: Request,
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

    # This is the only moment we know who the browser belongs to: GitHub has
    # just sent them back from a verified install. The cookie issued here is
    # what the dashboard checks from then on.
    response = RedirectResponse(f"/dashboard?installation_id={installation_id}", status_code=302)
    sessions.set_cookie(
        response, sessions.grant(request.cookies.get(sessions.COOKIE_NAME), installation_id)
    )
    return response


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
async def billing_upgrade(installation_id: int, request: Request, plan: str = "hobby"):
    if not _may_view(request, installation_id):
        return HTMLResponse(pages.not_your_installation(), status_code=403)

    if clerk_auth.configured():
        return RedirectResponse(
            f"/account?installation_id={installation_id}&plan={plan}", status_code=303
        )

    if plan not in billing.PLANS:
        raise HTTPException(status_code=400, detail="Choose Hobby or Pro")

    """Sends the user to Stripe Checkout. Only reachable after install - the
    trial is what keeps signup itself card-free."""
    base = PUBLIC_URL or str(request.base_url).rstrip("/")
    url = await billing.create_checkout_session(
        installation_id,
        plan,
        success_url=f"{base}/dashboard?installation_id={installation_id}",
        cancel_url=f"{base}/dashboard?installation_id={installation_id}",
    )
    if url is None:
        return HTMLResponse(pages.billing_unconfigured(), status_code=503)
    return RedirectResponse(url, status_code=302)


@app.get("/account", response_class=HTMLResponse)
def account(installation_id: int, request: Request, plan: str = "hobby") -> HTMLResponse:
    """Clerk sign-in shell for starting a paid checkout."""
    if not _may_view(request, installation_id):
        return HTMLResponse(pages.not_your_installation(), status_code=403)
    if plan not in billing.PLANS:
        plan = "hobby"
    return HTMLResponse(pages.account_page(installation_id, clerk_auth.publishable_key(), plan))


@app.post("/billing/checkout")
async def billing_checkout(request: Request):
    """Create Checkout only after both GitHub access and Clerk identity pass."""
    user = clerk_auth.user_id(request)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in required")
    payload = await request.json()
    try:
        installation_id = int(payload["installation_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="installation_id is required") from exc
    if not _may_view(request, installation_id):
        raise HTTPException(status_code=403, detail="Installation access required")
    plan = payload.get("plan", "hobby")
    if plan not in billing.PLANS:
        raise HTTPException(status_code=400, detail="Choose Hobby or Pro")

    base = PUBLIC_URL or str(request.base_url).rstrip("/")
    url = await billing.create_checkout_session(
        installation_id,
        plan,
        success_url=f"{base}/dashboard?installation_id={installation_id}",
        cancel_url=f"{base}/account?installation_id={installation_id}",
    )
    if url is None:
        raise HTTPException(status_code=503, detail="Billing is not configured")
    return {"url": url}


@app.post("/billing/webhook")
async def billing_webhook(request: Request, stripe_signature: str = Header(default="")) -> JSONResponse:
    body = await request.body()
    if not billing.verify_webhook_signature(body, stripe_signature):
        raise HTTPException(status_code=401, detail="Bad signature")

    outcome = billing.apply_event(await request.json())
    if outcome:
        print(f"paracheck: {outcome}")
    return JSONResponse({"ok": True})


@app.get("/enterprise", response_class=HTMLResponse)
def enterprise() -> HTMLResponse:
    return HTMLResponse(pages.enterprise_page(SALES_EMAIL))


@app.get("/", response_class=HTMLResponse)
def landing() -> HTMLResponse:
    return HTMLResponse(pages.landing(CHAIN))


@app.get("/pricing", response_class=HTMLResponse)
def pricing(request: Request, installation_id: int | None = None) -> HTMLResponse:
    """Public. An installation_id only changes which button is shown, and it is
    honoured only when this browser actually holds a session for it."""
    if installation_id is not None and not _may_view(request, installation_id):
        installation_id = None
    return HTMLResponse(pages.pricing_page(SALES_EMAIL, installation_id))


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request, installation_id: int | None = None, notice: str | None = None
) -> HTMLResponse:
    if installation_id is None:
        return HTMLResponse(pages.no_installation(), status_code=400)

    # Installation ids are small sequential integers, so without this the
    # dashboard is a directory of other people's repositories.
    if not _may_view(request, installation_id):
        return HTMLResponse(pages.not_your_installation(), status_code=403)

    installation = store.get_installation(installation_id)
    if installation is None:
        return HTMLResponse(pages.unknown_installation(), status_code=404)

    try:
        queue = job_queue.stats()
    except Exception:  # noqa: BLE001 - the dashboard must render even if the queue can't be read
        queue = {}

    return HTMLResponse(pages.installation_page(
        installation=installation,
        installation_id=installation_id,
        repos=store.active_repositories(installation_id),
        reviews=store.recent_reviews(installation_id, 25),
        scans=store.scan_statuses(installation_id),
        queue=queue,
        settings=_settings(),
        quota=store.quota_status(installation_id),
        csrf=sessions.csrf_token(installation_id),
        notice=NOTICES.get(notice),
    ))


# Kept server-side and referenced by name, so the redirect after saving a key
# can't be turned into a way to render arbitrary text on someone's dashboard.
NOTICES = {
    "saved": ("ok", "Key saved and verified against the Anthropic API."),
    "removed": ("ok", "Key removed. Reviews will be rendered from findings."),
    "rejected": ("error", "That key was rejected by the Anthropic API and has not been saved."),
    "unavailable": ("error", "This deployment can't store keys: no encryption secret is configured."),
    "missing": ("error", "No key was submitted."),
    "scanning": ("ok", "Scanning the default branch. The result appears here and as a "
                       "check on the commit, usually within a couple of minutes."),
    "quota": ("error", "That scan was not started - this week's quota is used up."),
    "unknown_repo": ("error", "ParaCheck doesn't have access to that repository."),
}


@app.post("/scan")
async def scan_repository(
    request: Request,
    installation_id: int = Form(...),
    full_name: str = Form(...),
    csrf: str = Form(""),
) -> RedirectResponse:
    """The "Scan now" button: analyse a repository's default branch without
    waiting for a pull request.

    This is the first useful thing a new installation can do, so it refuses
    clearly rather than silently queueing work that will be rejected later."""
    if not _may_view(request, installation_id):
        return HTMLResponse(pages.not_your_installation(), status_code=403)
    if not sessions.csrf_valid(installation_id, csrf):
        raise HTTPException(status_code=400, detail="Stale form - reload the dashboard.")

    back = f"/dashboard?installation_id={installation_id}"

    # The repository must be one GitHub actually granted us, not just a name
    # someone posted: otherwise this is a way to point the worker at any repo
    # the installation token can reach.
    if not store.is_repository_active(installation_id, full_name):
        return RedirectResponse(f"{back}&notice=unknown_repo", status_code=303)

    allowed, reason = store.review_allowed(installation_id)
    if not allowed:
        store.record_scan_outcome(installation_id, full_name, "blocked", reason)
        return RedirectResponse(f"{back}&notice=quota", status_code=303)

    store.record_scan_outcome(installation_id, full_name, "queued", "Waiting for a worker.")
    job_queue.enqueue(
        "scan_repository",
        {
            "installation_id": installation_id,
            "full_name": full_name,
            "min_severity": MIN_SEVERITY,
            "fail_on": FAIL_ON,
            "chain": CHAIN,
        },
        dedupe_key=f"scan:{full_name}",
    )
    return RedirectResponse(f"{back}&notice=scanning", status_code=303)


@app.post("/settings/api-key")
async def set_api_key(
    request: Request,
    installation_id: int = Form(...),
    csrf: str = Form(""),
    api_key: str = Form(""),
    action: str = Form("save"),
) -> RedirectResponse:
    """Stores an installation's own Anthropic key.

    The plaintext exists only for the length of this request: it is checked
    against the API, encrypted, and never logged or echoed back. The redirect
    carries a notice name rather than any part of the key."""
    if not _may_view(request, installation_id):
        return HTMLResponse(pages.not_your_installation(), status_code=403)
    back = f"/dashboard?installation_id={installation_id}"
    if not _claude_enabled():
        return RedirectResponse(f"{back}&notice=unavailable", status_code=303)
    if not sessions.csrf_valid(installation_id, csrf):
        raise HTTPException(status_code=400, detail="Stale form - reload the dashboard.")

    if action == "remove":
        store.set_anthropic_key(installation_id, None)
        return RedirectResponse(f"{back}&notice=removed", status_code=303)

    api_key = api_key.strip()
    if not api_key:
        return RedirectResponse(f"{back}&notice=missing", status_code=303)
    if not secrets_store.available():
        return RedirectResponse(f"{back}&notice=unavailable", status_code=303)

    ok, _reason = await asyncio.to_thread(_check_key, api_key)
    if not ok:
        return RedirectResponse(f"{back}&notice=rejected", status_code=303)

    store.set_anthropic_key(installation_id, api_key)
    return RedirectResponse(f"{back}&notice=saved", status_code=303)


def _check_key(api_key: str) -> tuple[bool, str]:
    try:
        from synthesize import check_key
    except ImportError:
        return False, "The synthesis module isn't installed on this deployment."
    return check_key(api_key)


def _may_view(request: Request, installation_id: int) -> bool:
    return installation_id in sessions.read(request.cookies.get(sessions.COOKIE_NAME))


def _settings() -> dict:
    """What this deployment is configured to do, for the dashboard to show."""
    return {
        "chain": CHAIN,
        "min_severity": MIN_SEVERITY,
        "fail_on": FAIL_ON,
        "billing": billing.configured(),
        "byok": _claude_enabled() and secrets_store.available(),
        "claude_enabled": _claude_enabled(),
        "inline_worker": INLINE_WORKER,
        "llm": _claude_enabled() and _llm_configured(),
        "clerk": clerk_auth.configured(),
    }


def _claude_enabled() -> bool:
    return os.environ.get("PARACHECK_CLAUDE_ENABLED", "0").lower() in ("1", "true", "yes")


def _llm_configured() -> bool:
    try:
        from synthesize import credentials_available

        return credentials_available()
    except Exception:  # noqa: BLE001 - absence of the analyzer path is not a dashboard error
        return False
