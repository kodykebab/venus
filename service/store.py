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

# Free reviews a new installation gets. Interpolated into the schema so the
# number the landing page advertises can't drift from the number granted.
TRIAL_REVIEWS = 50

SCHEMA = """
CREATE TABLE IF NOT EXISTS installations (
    id              INTEGER PRIMARY KEY,
    account_login   TEXT NOT NULL,
    account_type    TEXT NOT NULL DEFAULT 'User',
    active          INTEGER NOT NULL DEFAULT 1,
    trial_reviews   INTEGER NOT NULL DEFAULT {trial_reviews},
    plan            TEXT NOT NULL DEFAULT 'trial',
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
        # Trial accounts burn one review per run; paid plans are unmetered here.
        connection.execute(
            """
            UPDATE installations
               SET trial_reviews = MAX(trial_reviews - 1, 0), updated_at = ?
             WHERE id = ? AND plan = 'trial'
            """,
            (int(time.time()), installation_id),
        )


def recent_reviews(installation_id: int, limit: int = 20, db_path: str | None = None) -> list[dict]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM reviews WHERE installation_id = ? ORDER BY created_at DESC LIMIT ?",
            (installation_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]


def review_allowed(installation_id: int, db_path: str | None = None) -> tuple[bool, str]:
    """Trial accounts get a fixed number of reviews; paid plans are unlimited.
    Returns (allowed, reason) so the caller can post a useful check-run message
    rather than silently doing nothing."""
    installation = get_installation(installation_id, db_path)
    if installation is None:
        return False, "This installation is not registered."
    if not installation["active"]:
        return False, "This installation is no longer active."
    if installation["plan"] != "trial":
        return True, ""
    if installation["trial_reviews"] <= 0:
        return False, "Trial exhausted - subscribe to keep reviewing pull requests."
    return True, ""


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
