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
    for module in ("store", "app", "jobs", "github_auth"):
        sys.modules.pop(module, None)
    import store

    store.init_db()
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

def test_pull_request_schedules_a_review(client, monkeypatch):
    import app as service_app

    scheduled = []
    monkeypatch.setattr(
        service_app.jobs, "run_review_job",
        lambda *args, **kwargs: scheduled.append(args),
    )

    payload = {
        "action": "opened",
        "installation": {"id": 11},
        "repository": {"full_name": "acme/repo"},
        "pull_request": {"number": 3, "head": {"sha": "abc123"}},
    }
    assert post_webhook(client, "pull_request", payload).status_code == 200
    assert scheduled and scheduled[0][:4] == (11, "acme/repo", 3, "abc123")


def test_irrelevant_pull_request_actions_are_ignored(client, monkeypatch):
    import app as service_app

    scheduled = []
    monkeypatch.setattr(
        service_app.jobs, "run_review_job",
        lambda *args, **kwargs: scheduled.append(args),
    )
    payload = {
        "action": "labeled",
        "installation": {"id": 11},
        "repository": {"full_name": "acme/repo"},
        "pull_request": {"number": 3, "head": {"sha": "abc123"}},
    }
    assert post_webhook(client, "pull_request", payload).status_code == 200
    assert scheduled == []


# --- dashboard --------------------------------------------------------------

def test_dashboard_shows_repositories_and_quota(client):
    import store

    store.upsert_installation(12, "acme", "User")
    store.set_repositories(12, ["acme/repo"])
    store.record_review(12, "acme/repo", 5, "sha", "comment", 2)

    body = client.get("/dashboard?installation_id=12").text
    assert "acme/repo" in body
    assert "reviews left" in body
    assert "comment" in body
