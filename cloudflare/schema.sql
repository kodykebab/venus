-- ParaCheck control-plane schema (Cloudflare D1).
--
-- Two identities, deliberately separate tables:
--   accounts      - who pays (Clerk user or organisation)
--   installations - what we may read (a GitHub App installation)
-- They are linked, not merged: one account can own several installations
-- (personal plus a couple of orgs), and an installation exists from the moment
-- GitHub creates it, which is before anyone has signed in to pay for it.
--
-- Quota is counted from the `scans` table over a rolling seven days rather than
-- stored as a balance. A balance has to be replenished by something, and when
-- that something is a Stripe webhook that never arrived, a paying customer is
-- throttled to zero until a human notices.

CREATE TABLE IF NOT EXISTS accounts (
  id                     TEXT PRIMARY KEY,          -- Clerk user_... or org_...
  kind                   TEXT NOT NULL DEFAULT 'user',
  email                  TEXT,
  plan                   TEXT NOT NULL DEFAULT 'unpaid',
  stripe_customer_id     TEXT,
  stripe_subscription_id TEXT,
  -- Bring-your-own Claude key. Encrypted with a key held in Worker secrets, so
  -- a leaked database export is not a leak of every customer's Anthropic key.
  anthropic_key          TEXT,
  anthropic_key_hint     TEXT,                      -- last 4 chars, for the UI
  created_at             INTEGER NOT NULL,
  updated_at             INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS accounts_by_stripe_customer
  ON accounts (stripe_customer_id);

CREATE TABLE IF NOT EXISTS installations (
  id            INTEGER PRIMARY KEY,                -- GitHub installation id
  account_id    TEXT REFERENCES accounts(id),       -- null until someone claims it
  account_login TEXT NOT NULL,
  account_type  TEXT NOT NULL DEFAULT 'User',
  active        INTEGER NOT NULL DEFAULT 1,
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS installations_by_account
  ON installations (account_id);

CREATE TABLE IF NOT EXISTS repositories (
  installation_id INTEGER NOT NULL,
  full_name       TEXT NOT NULL,
  active          INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (installation_id, full_name)
);

-- Every scan, queued or finished. This is both the history the dashboard shows
-- and the ledger the quota is counted from.
CREATE TABLE IF NOT EXISTS scans (
  id              TEXT PRIMARY KEY,                 -- uuid, also the job id
  account_id      TEXT NOT NULL,
  installation_id INTEGER NOT NULL,
  repository      TEXT NOT NULL,
  pull_request    INTEGER,                          -- null for a branch scan
  head_sha        TEXT,
  trigger         TEXT NOT NULL DEFAULT 'pull_request',  -- pull_request | manual
  state           TEXT NOT NULL,                    -- queued|running|done|failed|blocked|empty
  findings        INTEGER NOT NULL DEFAULT 0,
  verdict         TEXT,
  message         TEXT,
  created_at      INTEGER NOT NULL,
  completed_at    INTEGER
);

CREATE INDEX IF NOT EXISTS scans_by_account
  ON scans (account_id, created_at DESC);

-- The quota query: count an account's scans inside the window. Indexed so it
-- stays a range scan rather than a table scan as history grows.
CREATE INDEX IF NOT EXISTS scans_for_quota
  ON scans (account_id, created_at);

CREATE INDEX IF NOT EXISTS scans_by_installation
  ON scans (installation_id, created_at DESC);

-- Webhook idempotency. Stripe and GitHub both retry, and a retried
-- `checkout.session.completed` must not be able to grant a second period.
CREATE TABLE IF NOT EXISTS webhook_events (
  provider    TEXT NOT NULL,
  event_id    TEXT NOT NULL,
  received_at INTEGER NOT NULL,
  PRIMARY KEY (provider, event_id)
);

-- Single-use CSRF state for the GitHub install redirect.
CREATE TABLE IF NOT EXISTS install_states (
  state      TEXT PRIMARY KEY,
  account_id TEXT,                                  -- who started the install
  created_at INTEGER NOT NULL
);
