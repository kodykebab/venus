"""Persistence for installations, OAuth state, and review history.

SQLite via the stdlib: a single-file database is enough for v1 and keeps the
service deployable without standing up infrastructure. Every query goes through
this module, so swapping in Postgres later is a change to one file.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
import time
from contextlib import contextmanager

DEFAULT_DB_PATH = os.environ.get("PARACHECK_DB", "paracheck.db")

# OAuth state is single-use and short-lived; anything older is a replay attempt
# or an abandoned install.
STATE_TTL_SECONDS = 600

# New installations are unpaid. Paid plans replenish this balance when Stripe
# confirms checkout; there is deliberately no free entitlement.
TRIAL_REVIEWS = 0

SCHEMA = """
CREATE TABLE IF NOT EXISTS installations (
    id              INTEGER PRIMARY KEY,
    account_login   TEXT NOT NULL,
    account_type    TEXT NOT NULL DEFAULT 'User',
    active          INTEGER NOT NULL DEFAULT 1,
    trial_reviews   INTEGER NOT NULL DEFAULT {trial_reviews},
    plan            TEXT NOT NULL DEFAULT 'unpaid',
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS repositories (
    installation_id INTEGER NOT NULL,
    full_name       TEXT NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (installation_id, full_name)
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state      TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    installation_id INTEGER NOT NULL,
    full_name       TEXT NOT NULL,
    pr_number       INTEGER,
    head_sha        TEXT,
    verdict         TEXT,
    findings        INTEGER NOT NULL DEFAULT 0,
    created_at      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS reviews_by_installation ON reviews (installation_id, created_at DESC);

-- The state of an on-demand "scan this repo" request. One row per repository:
-- only the latest attempt matters, and the history of completed scans already
-- lives in `reviews`.
CREATE TABLE IF NOT EXISTS scan_status (
    installation_id INTEGER NOT NULL,
    full_name       TEXT NOT NULL,
    state           TEXT NOT NULL,
    message         TEXT,
    updated_at      INTEGER NOT NULL,
    PRIMARY KEY (installation_id, full_name)
);
""".format(trial_reviews=TRIAL_REVIEWS)


@contextmanager
def connect(db_path: str | None = None):
    connection = sqlite3.connect(db_path or DEFAULT_DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


# Columns added after the first release. SQLite has no "ADD COLUMN IF NOT
# EXISTS", so they are applied by inspecting the table - an existing deployment
# must survive a redeploy without a manual migration step.
ADDED_COLUMNS = {
    "installations": {
        "anthropic_key": "TEXT",       # encrypted; see secrets_store.py
        "anthropic_key_hint": "TEXT",  # last 4 characters, for the dashboard
    },
}


def init_db(db_path: str | None = None) -> None:
    with connect(db_path) as connection:
        connection.executescript(SCHEMA)
        for table, columns in ADDED_COLUMNS.items():
            existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            for column, definition in columns.items():
                if column not in existing:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


# --- OAuth CSRF state -------------------------------------------------------

def issue_state(db_path: str | None = None) -> str:
    """Mints a single-use token for the install link. Verifying it on the way
    back is what stops an attacker linking their installation to someone else's
    account."""
    state = secrets.token_urlsafe(32)
    now = int(time.time())
    with connect(db_path) as connection:
        connection.execute("DELETE FROM oauth_states WHERE created_at < ?", (now - STATE_TTL_SECONDS,))
        connection.execute("INSERT INTO oauth_states (state, created_at) VALUES (?, ?)", (state, now))
    return state


def consume_state(state: str, db_path: str | None = None) -> bool:
    """True only if this exact state was issued, hasn't expired, and hasn't been
    used before. Deletes it either way - a state is good for one callback."""
    if not state:
        return False
    now = int(time.time())
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT created_at FROM oauth_states WHERE state = ?", (state,)
        ).fetchone()
        connection.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        if row is None:
            return False
        return (now - row["created_at"]) <= STATE_TTL_SECONDS


# --- Installations ----------------------------------------------------------

def upsert_installation(
    installation_id: int,
    account_login: str,
    account_type: str = "User",
    db_path: str | None = None,
) -> None:
    now = int(time.time())
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO installations (id, account_login, account_type, active, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                account_login = excluded.account_login,
                account_type  = excluded.account_type,
                active        = 1,
                updated_at    = excluded.updated_at
            """,
            (installation_id, account_login, account_type, now, now),
        )


def deactivate_installation(installation_id: int, db_path: str | None = None) -> None:
    with connect(db_path) as connection:
        connection.execute(
            "UPDATE installations SET active = 0, updated_at = ? WHERE id = ?",
            (int(time.time()), installation_id),
        )
        connection.execute(
            "UPDATE repositories SET active = 0 WHERE installation_id = ?", (installation_id,)
        )


def get_installation(installation_id: int, db_path: str | None = None) -> dict | None:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM installations WHERE id = ?", (installation_id,)
        ).fetchone()
        return dict(row) if row else None


# --- Repositories -----------------------------------------------------------

def set_repositories(installation_id: int, full_names: list[str], db_path: str | None = None) -> None:
    with connect(db_path) as connection:
        for full_name in full_names:
            connection.execute(
                """
                INSERT INTO repositories (installation_id, full_name, active) VALUES (?, ?, 1)
                ON CONFLICT(installation_id, full_name) DO UPDATE SET active = 1
                """,
                (installation_id, full_name),
            )


def remove_repositories(installation_id: int, full_names: list[str], db_path: str | None = None) -> None:
    with connect(db_path) as connection:
        for full_name in full_names:
            connection.execute(
                "UPDATE repositories SET active = 0 WHERE installation_id = ? AND full_name = ?",
                (installation_id, full_name),
            )


def active_repositories(installation_id: int, db_path: str | None = None) -> list[str]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT full_name FROM repositories WHERE installation_id = ? AND active = 1 ORDER BY full_name",
            (installation_id,),
        ).fetchall()
        return [row["full_name"] for row in rows]


def is_repository_active(installation_id: int, full_name: str, db_path: str | None = None) -> bool:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT active FROM repositories WHERE installation_id = ? AND full_name = ?",
            (installation_id, full_name),
        ).fetchone()
        return bool(row and row["active"])


# --- Review history / quota -------------------------------------------------

def record_review(
    installation_id: int,
    full_name: str,
    pr_number: int | None,
    head_sha: str | None,
    verdict: str | None,
    findings: int,
    db_path: str | None = None,
) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO reviews (installation_id, full_name, pr_number, head_sha, verdict, findings, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (installation_id, full_name, pr_number, head_sha, verdict, findings, int(time.time())),
        )
        # Nothing is decremented here: quota is counted from these rows, so
        # inserting one is the whole accounting step.


def recent_reviews(installation_id: int, limit: int = 20, db_path: str | None = None) -> list[dict]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM reviews WHERE installation_id = ? ORDER BY created_at DESC LIMIT ?",
            (installation_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]


# Quota is a rolling seven-day window, counted from the reviews actually run,
# rather than a counter granted at checkout and decremented.
#
# Counting is what makes the quota correct without a scheduled job and without
# depending on Stripe telling us a period rolled over: a missed `invoice.paid`
# used to mean an account was throttled to zero until someone noticed. A rolling
# window also can't be gamed by waiting for a reset and burning a month's quota
# in one minute.
QUOTA_WINDOW_SECONDS = 7 * 24 * 3600


def reviews_in_window(installation_id: int, db_path: str | None = None) -> int:
    since = int(time.time()) - QUOTA_WINDOW_SECONDS
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS n FROM reviews WHERE installation_id = ? AND created_at >= ?",
            (installation_id, since),
        ).fetchone()
        return row["n"]


def quota_resets_at(installation_id: int, db_path: str | None = None) -> int | None:
    """When the next unit frees up: the moment the oldest review in the window
    ages out of it."""
    since = int(time.time()) - QUOTA_WINDOW_SECONDS
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT MIN(created_at) AS oldest FROM reviews "
            "WHERE installation_id = ? AND created_at >= ?",
            (installation_id, since),
        ).fetchone()
    if row is None or row["oldest"] is None:
        return None
    return int(row["oldest"]) + QUOTA_WINDOW_SECONDS


def quota_status(installation_id: int, db_path: str | None = None) -> dict:
    """Everything a dashboard or a check run needs to explain the quota."""
    import billing

    installation = get_installation(installation_id, db_path)
    plan = installation["plan"] if installation else "unpaid"
    limit = billing.review_limit(plan)
    used = reviews_in_window(installation_id, db_path)
    return {
        "plan": plan,
        "limit": limit,
        "used": used,
        "remaining": max(limit - used, 0) if limit is not None else None,
        "resets_at": quota_resets_at(installation_id, db_path),
    }


def review_allowed(installation_id: int, db_path: str | None = None) -> tuple[bool, str]:
    """Only paid installations with quota left in the current window may run."""
    import billing

    installation = get_installation(installation_id, db_path)
    if installation is None:
        return False, "This installation is not registered."
    if not installation["active"]:
        return False, "This installation is no longer active."

    plan = installation["plan"]
    limit = billing.review_limit(plan)
    if limit is None:
        return True, ""  # enterprise: quota is agreed in the contract, not here
    if limit == 0:
        # Unpaid, lapsed, or a plan name we don't recognise. Say what to do
        # rather than reporting a quota of zero, which reads like a bug.
        return False, "Choose a Hobby or Pro plan to start reviewing pull requests."

    used = reviews_in_window(installation_id, db_path)
    if used >= limit:
        resets = quota_resets_at(installation_id, db_path)
        when = f" Quota frees up in {_until(resets)}." if resets else ""
        return False, (
            f"This week's quota is used up ({used}/{limit} scans in the last 7 days).{when}"
        )
    return True, ""


def _until(timestamp: int | None) -> str:
    if not timestamp:
        return "a moment"
    seconds = max(int(timestamp) - int(time.time()), 0)
    if seconds < 3600:
        return f"{max(seconds // 60, 1)} minutes"
    if seconds < 86400:
        return f"{seconds // 3600} hours"
    return f"{seconds // 86400} days"


# --- per-installation API keys ----------------------------------------------

def set_anthropic_key(
    installation_id: int, key: str | None, db_path: str | None = None
) -> None:
    """Stores an installation's Anthropic key, encrypted, or clears it when
    given None. The plaintext is never written anywhere - not to the database,
    not to a log line."""
    import secrets_store

    encrypted = secrets_store.encrypt(key) if key else None
    hint = secrets_store.hint(key) if key else None
    with connect(db_path) as connection:
        connection.execute(
            "UPDATE installations SET anthropic_key = ?, anthropic_key_hint = ?, "
            "updated_at = ? WHERE id = ?",
            (encrypted, hint, int(time.time()), installation_id),
        )


def anthropic_key(installation_id: int, db_path: str | None = None) -> str | None:
    """The decrypted key for a review job, or None to fall back to the
    deployment's own credentials."""
    import secrets_store

    installation = get_installation(installation_id, db_path)
    if installation is None:
        return None
    return secrets_store.decrypt(installation["anthropic_key"])


# --- on-demand scan state ---------------------------------------------------

def record_scan_outcome(
    installation_id: int, full_name: str, state: str, message: str = "",
    db_path: str | None = None,
) -> None:
    """State of the latest scan request for a repository: queued, done, failed,
    blocked or empty. Upserted because only the newest attempt is interesting."""
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO scan_status (installation_id, full_name, state, message, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(installation_id, full_name) DO UPDATE SET
                state = excluded.state,
                message = excluded.message,
                updated_at = excluded.updated_at
            """,
            (installation_id, full_name, state, message[:500], int(time.time())),
        )


def scan_statuses(installation_id: int, db_path: str | None = None) -> dict[str, dict]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM scan_status WHERE installation_id = ?", (installation_id,)
        ).fetchall()
        return {row["full_name"]: dict(row) for row in rows}
