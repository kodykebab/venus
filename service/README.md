# ParaCheck CI service

A GitHub App that reviews every pull request touching Solidity: one click to
install, then a Check Run with inline annotations on each finding.

No manual workflow file, no token pasting. The install link handles login,
repository selection, and the permission grant in GitHub's own UI, and returns
both an `installation_id` and an OAuth `code` — so the user is logged in and
installed in a single step.

## 1. Register the GitHub App

This part happens in GitHub's UI, once. **Settings → Developer settings → GitHub Apps → New GitHub App.**

| Field | Value |
|---|---|
| Name | `ParaCheck CI` (the slug becomes `GITHUB_APP_SLUG`) |
| Homepage URL | your site |
| **Setup URL** | `https://<your-host>/setup` |
| **Callback URL** | `https://<your-host>/setup` (same endpoint) |
| **Request user authorization (OAuth) during installation** | ✅ **on** — this is what makes it one click |
| Webhook URL | `https://<your-host>/webhook` |
| Webhook secret | generate one; it becomes `GITHUB_WEBHOOK_SECRET` |

**Permissions** (least privilege — this list is shown to users before they install, so every extra scope costs trust):

| Permission | Access | Why |
|---|---|---|
| Checks | Read & write | Create the check run and its annotations |
| Contents | Read-only | Clone the PR head to analyze it |
| Pull requests | Read & write | List changed files; comment |
| Metadata | Read-only | Mandatory default |

**Subscribe to events:** `installation`, `installation_repositories`, `pull_request`.

Then **generate a private key** and download the `.pem`.

## 2. Configure

```bash
cp service/.env.example service/.env   # then fill it in
```

| Variable | Required | Notes |
|---|---|---|
| `GITHUB_APP_ID` | yes | From the App's settings page |
| `GITHUB_APP_PRIVATE_KEY` | yes* | The PEM contents (`\n` escapes are handled) |
| `GITHUB_APP_PRIVATE_KEY_PATH` | yes* | ...or a path to the `.pem` instead |
| `GITHUB_WEBHOOK_SECRET` | yes | Must match what you set on the App |
| `GITHUB_CLIENT_ID` | yes | For the OAuth code exchange |
| `GITHUB_CLIENT_SECRET` | yes | " |
| `GITHUB_APP_SLUG` | yes | The URL slug, e.g. `paracheck-ci` |
| `ANTHROPIC_API_KEY` | no | Enables Claude synthesis; without it reviews still post, rendered from raw findings |
| `PARACHECK_DB` | no | SQLite path (default `paracheck.db`) |
| `PARACHECK_MIN_SEVERITY` | no | Drop findings below this (default `low`) |
| `PARACHECK_FAIL_ON` | no | Fail the check at or above this severity |

\* one of the two key variables.

**Never commit any of these.** The private key and webhook secret are the two
credentials that let someone impersonate the App outright.

## 3. Run

```bash
pip install -r service/requirements.txt -r analyzer/static/requirements.txt
cd service && uvicorn app:app --port 8000
```

The worker also needs `git`, `forge` (Foundry), and `solc` on PATH — it installs
each reviewed project's dependencies and compiles it.

For local development, point the webhook at a tunnel (`gh webhook forward` or
ngrok) rather than deploying on every change.

## 4. Install it somewhere

Send a user to `/install`. That's the whole flow:

1. `/install` issues a single-use CSRF state and redirects to GitHub.
2. GitHub handles login, repo selection, and the permission grant.
3. GitHub calls `/setup` with `installation_id`, `code`, and `state`.
4. The service validates the state, exchanges the code, records the
   installation, and drops the user on `/dashboard`.
5. Every subsequent pull request fires the webhook and gets a review.

## Security notes

These are load-bearing, not boilerplate:

- **Webhook signatures are verified** (HMAC-SHA256, constant time) before a
  payload is parsed. Unsigned or mismatched requests get a 401.
- **The OAuth `state` is single-use and expires in 10 minutes.** Without this
  check, an attacker can trick a user into attaching their installation to the
  attacker's account.
- **Installation tokens are treated as opaque and short-lived** — minted per
  job, never cached, never pattern-matched. GitHub's stateless token format has
  no fixed length, so nothing here may assume one.
- **Clone URLs carry a token**, so git commands are never echoed, the remote is
  removed after checkout, and the working directory is deleted in a `finally`.
- **Dependency installation runs third-party build tooling.** Every subprocess
  is timeout-bounded, and the worker is expected to be disposable.

## Known gaps

- Reviews run as FastAPI background tasks. That's honest for v1 but means a
  restart drops in-flight work — a real queue is the next step.
- SQLite. Fine for one worker; swap `store.py` for Postgres before scaling out.
- Billing is modeled (trial counter, plan field) but there's no checkout flow
  wired up yet.
