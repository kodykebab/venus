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
                   "billing", "sessions", "secrets_store"):
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
    assert "reviews left" in body
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


def test_upgrade_is_honest_when_billing_is_unconfigured(client, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_PRICE_ID", raising=False)
    response = signed_in_for(client, 1).get(
        "/billing/upgrade?installation_id=1", follow_redirects=False
    )
    assert response.status_code == 503
    assert "trial-only mode" in response.text


def test_exhausted_trial_blocks_further_reviews(client):
    import store

    store.upsert_installation(78, "acme", "User")
    with store.connect() as connection:
        connection.execute("UPDATE installations SET trial_reviews = 0 WHERE id = 78")

    allowed, reason = store.review_allowed(78)
    assert allowed is False and "Trial exhausted" in reason

    # A paid plan lifts the gate.
    import billing

    billing.set_plan(78, "pro")
    assert store.review_allowed(78)[0] is True
