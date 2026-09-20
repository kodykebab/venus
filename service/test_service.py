"""Service tests, weighted toward the parts that are security-critical: webhook
signature verification and the install flow's CSRF state.
"""
import hashlib
import hmac
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SECRET = "test-webhook-secret"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    monkeypatch.setenv("PARACHECK_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("GITHUB_APP_SLUG", "paracheck-ci")
    # The inline worker would drain the queue (and hit the network) mid-test;
    # these tests assert on what gets queued, worker tests drive it directly.
    monkeypatch.setenv("PARACHECK_INLINE_WORKER", "0")
    # billing holds a module-level reference to store; leaving it cached would
    # leak the previous test's database into the next one.
    monkeypatch.setenv("PARACHECK_ENCRYPTION_KEY", "test-encryption-secret")
    for module in ("store", "app", "jobs", "jobqueue", "worker", "github_auth",
                   "billing", "sessions", "secrets_store", "clerk_auth"):
        sys.modules.pop(module, None)
    import jobqueue
    import store

    store.init_db()
    jobqueue.init_queue()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    import app as service_app

    return TestClient(service_app.app)


def signed(body: dict) -> tuple[bytes, str]:
    raw = json.dumps(body).encode()
    digest = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, f"sha256={digest}"


def post_webhook(client, event: str, payload: dict, signature: str | None = None):
    raw, good_signature = signed(payload)
    return client.post(
        "/webhook",
        content=raw,
        headers={
            "X-GitHub-Event": event,
            "X-Hub-Signature-256": signature if signature is not None else good_signature,
            "Content-Type": "application/json",
        },
    )


# --- webhook security -------------------------------------------------------

def test_unsigned_webhook_is_rejected(client):
    raw, _ = signed({"action": "created"})
    response = client.post("/webhook", content=raw, headers={"X-GitHub-Event": "installation"})
    assert response.status_code == 401


def test_webhook_with_wrong_signature_is_rejected(client):
    response = post_webhook(client, "installation", {"action": "created"}, signature="sha256=deadbeef")
    assert response.status_code == 401


def test_tampered_body_is_rejected(client):
    raw, signature = signed({"action": "created"})
    response = client.post(
        "/webhook",
        content=raw.replace(b"created", b"deleted"),
        headers={"X-GitHub-Event": "installation", "X-Hub-Signature-256": signature},
    )
    assert response.status_code == 401


# --- install flow -----------------------------------------------------------

def test_install_redirects_to_github_with_state(client):
    response = client.get("/install", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://github.com/apps/paracheck-ci/installations/new?state=")
    assert len(location.split("state=")[1]) > 20


def test_setup_rejects_a_forged_state(client):
    response = client.get("/setup?installation_id=1&state=forged", follow_redirects=False)
    assert response.status_code == 400


def test_setup_rejects_a_replayed_state(client):
    import store

    state = store.issue_state()
    first = client.get(f"/setup?installation_id=99&state={state}", follow_redirects=False)
    assert first.status_code == 302
    replay = client.get(f"/setup?installation_id=99&state={state}", follow_redirects=False)
    assert replay.status_code == 400, "a state must only ever work once"


def test_setup_records_the_installation(client):
    import store

    state = store.issue_state()
    response = client.get(f"/setup?installation_id=4242&state={state}", follow_redirects=False)
    assert response.status_code == 302
    assert "/dashboard?installation_id=4242" in response.headers["location"]
    assert store.get_installation(4242) is not None


# --- installation lifecycle -------------------------------------------------

def test_installation_created_records_repositories(client):
    import store

    payload = {
        "action": "created",
        "installation": {"id": 7, "account": {"login": "acme", "type": "Organization"}},
        "repositories": [{"full_name": "acme/one"}, {"full_name": "acme/two"}],
    }
    assert post_webhook(client, "installation", payload).status_code == 200
    assert store.active_repositories(7) == ["acme/one", "acme/two"]
    assert store.get_installation(7)["account_type"] == "Organization"


def test_uninstall_deactivates_everything(client):
    import store

    post_webhook(client, "installation", {
        "action": "created",
        "installation": {"id": 8, "account": {"login": "acme", "type": "User"}},
        "repositories": [{"full_name": "acme/one"}],
    })
    post_webhook(client, "installation", {"action": "deleted", "installation": {"id": 8}})

    assert store.active_repositories(8) == []
    allowed, reason = store.review_allowed(8)
    assert allowed is False and "no longer active" in reason


def test_repository_add_and_remove(client):
    import store

    post_webhook(client, "installation", {
        "action": "created",
        "installation": {"id": 9, "account": {"login": "acme", "type": "User"}},
        "repositories": [{"full_name": "acme/one"}],
    })
    post_webhook(client, "installation_repositories", {
        "action": "added",
        "installation": {"id": 9},
        "repositories_added": [{"full_name": "acme/two"}],
        "repositories_removed": [{"full_name": "acme/one"}],
    })
    assert store.active_repositories(9) == ["acme/two"]


# --- pull request dispatch --------------------------------------------------

def pull_request_payload(action="opened", number=3, sha="abc123"):
    return {
        "action": action,
        "installation": {"id": 11},
        "repository": {"full_name": "acme/repo"},
        "pull_request": {"number": number, "head": {"sha": sha}},
    }


def test_pull_request_queues_a_review(client):
    import jobqueue

    assert post_webhook(client, "pull_request", pull_request_payload()).status_code == 200

    job = jobqueue.claim()
    assert job is not None
    assert job.kind == "review_pull_request"
    assert job.payload["installation_id"] == 11
    assert job.payload["full_name"] == "acme/repo"
    assert job.payload["pr_number"] == 3
    assert job.payload["head_sha"] == "abc123"


def test_irrelevant_pull_request_actions_are_ignored(client):
    import jobqueue

    assert post_webhook(client, "pull_request", pull_request_payload("labeled")).status_code == 200
    assert jobqueue.claim() is None


def test_rapid_pushes_collapse_to_one_review_of_the_latest_head(client):
    """Pushing three times in a row should review the newest commit once, not
    queue three reviews of commits nobody is waiting on any more."""
    import jobqueue

    for sha in ("aaa", "bbb", "ccc"):
        post_webhook(client, "pull_request", pull_request_payload("synchronize", sha=sha))

    job = jobqueue.claim()
    assert job.payload["head_sha"] == "ccc"
    assert jobqueue.claim() is None


def test_separate_pull_requests_do_not_collapse(client):
    import jobqueue

    post_webhook(client, "pull_request", pull_request_payload(number=3))
    post_webhook(client, "pull_request", pull_request_payload(number=4))

    numbers = {jobqueue.claim().payload["pr_number"], jobqueue.claim().payload["pr_number"]}
    assert numbers == {3, 4}


def test_a_queued_review_survives_a_restart(client):
    """The reason this is a table and not BackgroundTasks: a redeploy between
    the webhook and the review must not silently drop the check."""
    import jobqueue

    post_webhook(client, "pull_request", pull_request_payload())

    for module in ("jobqueue", "store"):
        sys.modules.pop(module, None)
    import jobqueue as reloaded

    assert reloaded.claim().payload["pr_number"] == 3


# --- queue mechanics --------------------------------------------------------

def test_a_crashed_worker_releases_its_job():
    import jobqueue
    import store

    jobqueue.enqueue("review_pull_request", {"pr": 1})
    job = jobqueue.claim()
    assert jobqueue.claim() is None  # held by the (now dead) worker

    with store.connect() as connection:
        connection.execute("UPDATE jobs SET claimed_at = claimed_at - ?", (jobqueue.STALE_AFTER_SECONDS + 1,))

    assert jobqueue.claim().id == job.id


def test_a_failing_job_retries_then_parks():
    import jobqueue
    import store

    jobqueue.enqueue("review_pull_request", {"pr": 1})
    for attempt in range(1, jobqueue.MAX_ATTEMPTS + 1):
        job = jobqueue.claim()
        assert job is not None, f"expected a retry on attempt {attempt}"
        jobqueue.fail(job.id, "boom", job.attempts)
        with store.connect() as connection:
            connection.execute("UPDATE jobs SET run_after = 0")  # skip the backoff

    assert jobqueue.claim() is None
    assert jobqueue.stats() == {"failed": 1}


def test_an_unknown_job_kind_is_parked_not_retried():
    import asyncio

    import jobqueue
    import worker

    jobqueue.enqueue("nonsense", {})
    asyncio.run(worker.run_job(jobqueue.claim()))
    assert jobqueue.stats() == {"failed": 1}


def test_the_worker_completes_a_job_and_reports_failures(monkeypatch):
    import asyncio

    import jobqueue
    import worker

    ran = []
    monkeypatch.setitem(worker.HANDLERS, "review_pull_request", lambda **kw: ran.append(kw))
    jobqueue.enqueue("review_pull_request", {"pr_number": 7})
    asyncio.run(worker.run_job(jobqueue.claim()))
    assert ran == [{"pr_number": 7}] and jobqueue.stats() == {"done": 1}

    def explode(**_):
        raise RuntimeError("slither exploded")

    monkeypatch.setitem(worker.HANDLERS, "review_pull_request", explode)
    jobqueue.enqueue("review_pull_request", {"pr_number": 8})
    asyncio.run(worker.run_job(jobqueue.claim()))
    assert jobqueue.stats()["pending"] == 1  # retried, not lost


# --- dashboard --------------------------------------------------------------

def signed_in_for(client, installation_id: int):
    """The cookie the setup callback issues, without going through GitHub."""
    import sessions

    client.cookies.set(sessions.COOKIE_NAME, sessions.issue([installation_id]))
    return client


def test_dashboard_shows_repositories_and_quota(client):
    import store

    store.upsert_installation(12, "acme", "User")
    store.set_repositories(12, ["acme/repo"])
    store.record_review(12, "acme/repo", 5, "sha", "comment", 2)

    body = signed_in_for(client, 12).get("/dashboard?installation_id=12").text
    assert "acme/repo" in body
    assert "Choose a plan" in body
    assert "comment" in body


def test_setup_signs_the_browser_in_for_that_installation(client):
    """The setup callback is the only moment we know who the browser is, so it
    has to be the moment the session is issued."""
    import store

    response = client.get(
        f"/setup?installation_id=77&state={store.issue_state()}", follow_redirects=False
    )
    assert response.status_code == 302

    import sessions

    assert 77 in sessions.read(response.cookies.get(sessions.COOKIE_NAME))

    cookie = client.cookies.get(sessions.COOKIE_NAME)
    assert cookie, "the browser should now hold a session cookie"
    assert client.get("/dashboard?installation_id=77").status_code == 200
    assert client.get("/dashboard?installation_id=78").status_code == 403


# --- one-click repository scan ------------------------------------------------

def scan_form(client, installation_id, full_name, csrf=None):
    import sessions

    return client.post("/scan", data={
        "installation_id": str(installation_id),
        "full_name": full_name,
        "csrf": csrf if csrf is not None else sessions.csrf_token(installation_id),
    }, follow_redirects=False)


def paid_installation(installation_id, login="acme"):
    import billing
    import store

    store.upsert_installation(installation_id, login, "User")
    store.set_repositories(installation_id, [f"{login}/repo"])
    billing.set_plan(installation_id, "pro")
    return f"{login}/repo"


def test_scan_now_queues_a_default_branch_scan(client):
    """The first useful thing a new installation can do shouldn't be "wait for
    somebody to open a pull request"."""
    import jobqueue

    repo = paid_installation(90)
    signed_in_for(client, 90)

    response = scan_form(client, 90, repo)
    assert response.status_code == 303
    assert "notice=scanning" in response.headers["location"]

    job = jobqueue.claim()
    assert job is not None and job.kind == "scan_repository"
    assert job.payload["full_name"] == repo


def test_a_scan_cannot_be_pointed_at_a_repository_we_were_not_given(client):
    """The installation token can reach every repo GitHub granted; the form
    field must not be able to choose one that wasn't granted to this account."""
    import jobqueue
    import store

    paid_installation(91)
    signed_in_for(client, 91)

    response = scan_form(client, 91, "someone-else/private")
    assert "notice=unknown_repo" in response.headers["location"]
    assert jobqueue.claim() is None
    assert store.scan_statuses(91) == {}


def test_a_scan_needs_a_session_and_a_form_token(client):
    import jobqueue

    repo = paid_installation(92)

    signed_in_for(client, 999)
    assert scan_form(client, 92, repo).status_code == 403

    signed_in_for(client, 92)
    assert scan_form(client, 92, repo, csrf="forged").status_code == 400
    assert jobqueue.claim() is None


def test_an_exhausted_quota_refuses_the_scan_instead_of_queueing_it(client):
    """Queueing work that will be rejected minutes later by a worker is worse
    than saying no at the button."""
    import billing
    import jobqueue
    import store

    repo = paid_installation(93)
    billing.set_plan(93, "hobby")
    for pr in range(billing.review_limit("hobby")):
        store.record_review(93, repo, pr, "sha", "comment", 0)

    signed_in_for(client, 93)
    response = scan_form(client, 93, repo)
    assert "notice=quota" in response.headers["location"]
    assert jobqueue.claim() is None
    assert store.scan_statuses(93)[repo]["state"] == "blocked"


def test_repeated_clicks_do_not_queue_repeated_scans(client):
    import jobqueue

    repo = paid_installation(94)
    signed_in_for(client, 94)
    for _ in range(3):
        scan_form(client, 94, repo)

    assert jobqueue.claim() is not None
    assert jobqueue.claim() is None


def test_the_dashboard_offers_a_scan_button_for_each_repository(client):
    repo = paid_installation(95)
    signed_in_for(client, 95)
    page = client.get("/dashboard?installation_id=95").text
    assert "Scan now" in page
    assert f'value="{repo}"' in page


def test_dependency_directories_are_not_scanned(tmp_path):
    """A repo vendoring OpenZeppelin would otherwise submit hundreds of files."""
    import jobs

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Vault.sol").write_text("contract V {}")
    (tmp_path / "lib" / "forge-std").mkdir(parents=True)
    (tmp_path / "lib" / "forge-std" / "Test.sol").write_text("contract T {}")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "Dep.sol").write_text("contract D {}")

    assert jobs.solidity_files_in(str(tmp_path)) == ["src/Vault.sol"]


# --- access control -----------------------------------------------------------

def test_another_installations_dashboard_is_refused(client):
    """Installation ids are small sequential integers. Without a session check
    the dashboard is a directory of other people's repositories."""
    import store

    store.upsert_installation(31, "victim", "Organization")
    store.set_repositories(31, ["victim/secret-protocol"])

    response = signed_in_for(client, 99).get("/dashboard?installation_id=31")
    assert response.status_code == 403
    assert "victim/secret-protocol" not in response.text


def test_the_dashboard_needs_a_session_at_all(client):
    import store

    store.upsert_installation(32, "victim", "User")
    store.set_repositories(32, ["victim/secret-protocol"])

    response = client.get("/dashboard?installation_id=32")
    assert response.status_code == 403
    assert "victim/secret-protocol" not in response.text


def test_a_refusal_does_not_reveal_whether_the_installation_exists(client):
    import store

    store.upsert_installation(33, "victim", "User")
    real = client.get("/dashboard?installation_id=33")
    absent = client.get("/dashboard?installation_id=999999")
    assert real.status_code == absent.status_code == 403
    assert real.text == absent.text


def test_a_tampered_cookie_grants_nothing(client):
    import sessions

    token = sessions.issue([31])
    payload, _, signature = token.partition(".")
    forged = sessions.issue([31]).replace(payload, sessions.issue([32]).partition(".")[0])

    client.cookies.set(sessions.COOKIE_NAME, forged)
    assert client.get("/dashboard?installation_id=32").status_code == 403

    client.cookies.set(sessions.COOKIE_NAME, f"{payload}.{signature[:-4]}AAAA")
    assert client.get("/dashboard?installation_id=31").status_code == 403


def test_a_cookie_signed_with_another_secret_grants_nothing(client, monkeypatch):
    """A deployment's cookies must not be valid on another deployment."""
    import sessions

    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "somebody-elses-secret")
    forged = sessions.issue([31])
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)

    client.cookies.set(sessions.COOKIE_NAME, forged)
    assert client.get("/dashboard?installation_id=31").status_code == 403


def test_an_expired_session_grants_nothing(client, monkeypatch):
    import sessions

    token = sessions.issue([31])
    monkeypatch.setattr(sessions.time, "time", lambda: 10**9 + sessions.MAX_AGE_SECONDS + 10**9)
    assert sessions.read(token) == []


def test_installing_a_second_time_keeps_access_to_the_first(client):
    import sessions

    first = sessions.issue([41])
    both = sessions.grant(first, 42)
    assert sorted(sessions.read(both)) == [41, 42]


def test_billing_upgrade_refuses_another_installation(client):
    response = signed_in_for(client, 50).get(
        "/billing/upgrade?installation_id=51", follow_redirects=False
    )
    assert response.status_code == 403


# --- bring your own key -------------------------------------------------------

def api_key_form(client, installation_id, **fields):
    import sessions

    body = {
        "installation_id": str(installation_id),
        "csrf": sessions.csrf_token(installation_id),
        "action": "save",
        **fields,
    }
    return client.post("/settings/api-key", data=body, follow_redirects=False)


@pytest.fixture
def accepts_any_key(monkeypatch):
    """The key check makes a real API call; these tests are about everything
    around it."""
    import app as service_app

    monkeypatch.setenv("PARACHECK_CLAUDE_ENABLED", "1")
    monkeypatch.setattr(service_app, "_check_key", lambda key: (True, ""))


def test_a_key_is_stored_encrypted_and_never_shown_again(client, accepts_any_key):
    import secrets_store
    import store

    store.upsert_installation(60, "acme", "User")
    signed_in_for(client, 60)

    assert api_key_form(client, 60, api_key="sk-ant-api03-SUPERSECRET").status_code == 303

    row = store.get_installation(60)
    assert "SUPERSECRET" not in (row["anthropic_key"] or ""), "stored in the clear"
    assert secrets_store.decrypt(row["anthropic_key"]) == "sk-ant-api03-SUPERSECRET"
    assert row["anthropic_key_hint"] == "...CRET"

    page = client.get("/dashboard?installation_id=60").text
    assert "SUPERSECRET" not in page, "the key was echoed back into the page"
    assert "...CRET" in page, "no way to tell which key is installed"


def test_a_rejected_key_is_not_stored(client, monkeypatch):
    import app as service_app
    import store

    monkeypatch.setenv("PARACHECK_CLAUDE_ENABLED", "1")
    store.upsert_installation(61, "acme", "User")
    signed_in_for(client, 61)
    monkeypatch.setattr(service_app, "_check_key", lambda key: (False, "rejected"))

    response = api_key_form(client, 61, api_key="sk-ant-bogus")
    assert "notice=rejected" in response.headers["location"]
    assert store.anthropic_key(61) is None


def test_a_key_can_be_removed(client, accepts_any_key):
    import store

    store.upsert_installation(62, "acme", "User")
    signed_in_for(client, 62)
    api_key_form(client, 62, api_key="sk-ant-something")
    assert store.anthropic_key(62) is not None

    api_key_form(client, 62, action="remove", api_key="")
    assert store.anthropic_key(62) is None
    assert store.get_installation(62)["anthropic_key_hint"] is None


def test_setting_a_key_needs_a_session_for_that_installation(client, accepts_any_key):
    import store

    store.upsert_installation(63, "victim", "User")
    signed_in_for(client, 99)
    assert api_key_form(client, 63, api_key="sk-ant-attacker").status_code == 403
    assert store.anthropic_key(63) is None


def test_setting_a_key_needs_the_form_token(client, accepts_any_key):
    import store

    store.upsert_installation(64, "acme", "User")
    signed_in_for(client, 64)
    response = client.post("/settings/api-key", data={
        "installation_id": "64", "csrf": "forged", "api_key": "sk-ant-x", "action": "save",
    }, follow_redirects=False)
    assert response.status_code == 400
    assert store.anthropic_key(64) is None


def test_a_form_token_is_not_valid_for_another_installation(client):
    import sessions

    assert not sessions.csrf_valid(65, sessions.csrf_token(66))
    assert sessions.csrf_valid(65, sessions.csrf_token(65))


def test_the_notice_cannot_be_used_to_write_into_the_page(client):
    """The redirect carries a notice name, not text, so a crafted link can't
    render arbitrary content on somebody's dashboard."""
    import store

    store.upsert_installation(67, "acme", "User")
    signed_in_for(client, 67)
    page = client.get("/dashboard?installation_id=67&notice=<script>alert(1)</script>").text
    assert "<script>alert(1)</script>" not in page


def test_reviews_use_the_installations_own_key(monkeypatch):
    """One deployment, many accounts, each billing their own usage."""
    import jobs
    import store

    monkeypatch.setenv("PARACHECK_CLAUDE_ENABLED", "1")
    store.upsert_installation(68, "acme", "User")
    store.set_anthropic_key(68, "sk-ant-theirs")
    assert store.anthropic_key(68) == "sk-ant-theirs"

    seen = {}

    def fake_synthesize(report, api_key=None, **kwargs):
        seen["api_key"] = api_key
        return None

    import sys
    module = type(sys)("synthesize")
    module.synthesize_review = fake_synthesize
    module.render_synthesized = lambda *a, **k: ""
    monkeypatch.setitem(sys.modules, "synthesize", module)

    jobs._summarize({"findings": []}, ["a.sol"], store.anthropic_key(68))
    assert seen["api_key"] == "sk-ant-theirs"


def test_an_unreadable_key_degrades_instead_of_crashing(client, monkeypatch):
    """Rotating the encryption secret must not make every review throw."""
    import store

    store.upsert_installation(69, "acme", "User")
    store.set_anthropic_key(69, "sk-ant-old")

    monkeypatch.setenv("PARACHECK_ENCRYPTION_KEY", "a-different-secret")
    assert store.anthropic_key(69) is None


# --- billing ----------------------------------------------------------------

def test_account_requires_github_installation_access(client, monkeypatch):
    monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", "pk_test_public")
    monkeypatch.setenv("CLERK_JWT_KEY", "not-a-private-key")
    response = client.get("/account?installation_id=77")
    assert response.status_code == 403


def test_account_shell_exposes_only_the_clerk_publishable_key(client, monkeypatch):
    import store

    monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", "pk_test_public")
    monkeypatch.setenv("CLERK_JWT_KEY", "backend-secret-key")
    store.upsert_installation(78, "acme", "User")
    body = signed_in_for(client, 78).get("/account?installation_id=78").text
    assert "pk_test_public" in body
    assert "backend-secret-key" not in body
    assert "Continue to checkout" in body


def test_checkout_requires_a_verified_clerk_token(client, monkeypatch):
    import store

    monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", "pk_test_public")
    monkeypatch.setenv("CLERK_JWT_KEY", "not-a-private-key")
    store.upsert_installation(79, "acme", "User")
    response = signed_in_for(client, 79).post(
        "/billing/checkout", json={"installation_id": 79}
    )
    assert response.status_code == 401

def test_billing_webhook_rejects_bad_signature(client, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    response = client.post(
        "/billing/webhook",
        content=b'{"type":"checkout.session.completed"}',
        headers={"Stripe-Signature": "t=1,v1=deadbeef"},
    )
    assert response.status_code == 401


def test_billing_webhook_upgrades_the_installation(client, monkeypatch):
    import hashlib
    import hmac
    import time

    import billing
    import store

    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    store.upsert_installation(77, "acme", "User")

    payload = b'{"type":"checkout.session.completed","data":{"object":{"client_reference_id":"77"}}}'
    timestamp = int(time.time())
    digest = hmac.new(b"whsec_test", f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()

    response = client.post(
        "/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": f"t={timestamp},v1={digest}"},
    )
    assert response.status_code == 200
    assert billing.billing_status(77)["plan"] == "pro"


def test_quota_is_counted_over_a_rolling_week(client):
    """Quota is counted from the scans actually run, not granted at checkout,
    so it cannot be left stale by a Stripe event that never arrived."""
    import billing
    import store

    store.upsert_installation(76, "acme", "User")
    billing.set_plan(76, "hobby")
    limit = billing.review_limit("hobby")

    for pr in range(limit):
        assert store.review_allowed(76)[0] is True, f"blocked early at scan {pr}"
        store.record_review(76, "acme/repo", pr, "sha", "comment", 1)

    allowed, reason = store.review_allowed(76)
    assert allowed is False
    assert f"{limit}/{limit}" in reason
    assert store.quota_status(76)["remaining"] == 0


def test_quota_frees_up_as_scans_age_out(client):
    """No cron and no renewal event: a scan leaving the window is the reset."""
    import time

    import billing
    import store

    store.upsert_installation(77, "acme", "User")
    billing.set_plan(77, "hobby")
    for pr in range(billing.review_limit("hobby")):
        store.record_review(77, "acme/repo", pr, "sha", "comment", 0)
    assert store.review_allowed(77)[0] is False

    with store.connect() as connection:
        connection.execute(
            "UPDATE reviews SET created_at = ? WHERE pr_number = 0 AND installation_id = 77",
            (int(time.time()) - store.QUOTA_WINDOW_SECONDS - 60,),
        )

    assert store.review_allowed(77)[0] is True
    assert store.quota_status(77)["remaining"] == 1


def test_an_unpaid_account_is_told_to_pick_a_plan_not_shown_a_zero_quota(client):
    import store

    store.upsert_installation(79, "acme", "User")
    allowed, reason = store.review_allowed(79)
    assert allowed is False
    assert "Choose a" in reason
    assert "0/0" not in reason, "a quota of zero reads like a bug, not a paywall"


def test_enterprise_has_no_fixed_cap(client):
    import billing
    import store

    store.upsert_installation(80, "acme", "Organization")
    billing.set_plan(80, "enterprise")
    for pr in range(150):
        store.record_review(80, "acme/repo", pr, "sha", "comment", 0)
    assert store.review_allowed(80)[0] is True
    assert store.quota_status(80)["remaining"] is None


def test_a_renewal_restores_a_lapsed_account(client):
    """The gap this closes: quota used to be granted at checkout, so a missed
    recurring event left a paying account throttled to zero."""
    import billing
    import store

    store.upsert_installation(81, "acme", "User")
    billing.set_plan(81, "unpaid")

    billing.apply_event({"type": "invoice.paid", "data": {"object": {
        "subscription_details": {"metadata": {"installation_id": "81", "plan": "pro"}}}}})
    assert store.get_installation(81)["plan"] == "pro"

    billing.apply_event({"type": "customer.subscription.updated", "data": {"object": {
        "status": "canceled", "metadata": {"installation_id": "81", "plan": "pro"}}}})
    assert store.get_installation(81)["plan"] == "unpaid"


def test_plan_quotas_match_what_the_pricing_page_advertises(client):
    """One source of truth: the page reads billing.PLANS, and the gate reads the
    same numbers, so they cannot drift apart."""
    import billing
    import dashboard

    page = dashboard.pricing_page("sales@example.com")
    for key in billing.PLANS:
        details = billing.plan_details(key)
        assert details["price"] in page
        assert f"{details['review_limit']} scans per week" in page


def test_upgrade_is_honest_when_billing_is_unconfigured(client, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_HOBBY_PRICE_ID", raising=False)
    monkeypatch.delenv("STRIPE_PRO_PRICE_ID", raising=False)
    response = signed_in_for(client, 1).get(
        "/billing/upgrade?installation_id=1", follow_redirects=False
    )
    assert response.status_code == 503
    # Asserting on the substance, not the punctuation: esc() renders an
    # apostrophe as an entity, which is correct HTML but brittle to match.
    assert "no Stripe configuration" in response.text


def test_exhausted_trial_blocks_further_reviews(client):
    import store

    store.upsert_installation(78, "acme", "User")
    with store.connect() as connection:
        connection.execute("UPDATE installations SET trial_reviews = 0 WHERE id = 78")

    allowed, reason = store.review_allowed(78)
    assert allowed is False and "Choose a Hobby or Pro plan" in reason

    # A paid plan lifts the gate.
    import billing

    billing.set_plan(78, "pro")
    assert store.review_allowed(78)[0] is True
