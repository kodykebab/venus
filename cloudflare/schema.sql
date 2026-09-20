CREATE TABLE IF NOT EXISTS accounts (
  clerk_user_id TEXT PRIMARY KEY,
  github_installation_id INTEGER UNIQUE,
  plan TEXT NOT NULL DEFAULT 'unpaid',
  reviews_remaining INTEGER NOT NULL DEFAULT 0,
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_events (
  provider TEXT NOT NULL,
  event_id TEXT NOT NULL,
  received_at INTEGER NOT NULL,
  PRIMARY KEY (provider, event_id)
);

CREATE TABLE IF NOT EXISTS review_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  clerk_user_id TEXT NOT NULL,
  github_installation_id INTEGER NOT NULL,
  repository TEXT NOT NULL,
  pull_request INTEGER,
  head_sha TEXT,
  status TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  completed_at INTEGER
);

CREATE INDEX IF NOT EXISTS review_runs_by_account
  ON review_runs (clerk_user_id, created_at DESC);
