"""A durable job queue backed by the same database as everything else.

FastAPI BackgroundTasks lose in-flight work on restart or redeploy, which for a
review that takes minutes means a pull request silently never gets its check.
Jobs are rows instead: claimed atomically, retried on failure, and still there
after a crash.

Deliberately not Redis/Celery - one dependency-free table handles this load, and
the claim is a single atomic UPDATE, so multiple workers are safe.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import store

MAX_ATTEMPTS = 3
# Long enough for dependency install + compile + analysis; past this a job is
# assumed dead (worker killed mid-flight) and becomes claimable again.
STALE_AFTER_SECONDS = 1800
RETRY_BACKOFF_SECONDS = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL,
    payload       TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    claimed_at    INTEGER,
    run_after     INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL,
    dedupe_key    TEXT
);
CREATE INDEX IF NOT EXISTS jobs_claimable ON jobs (status, run_after);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_dedupe ON jobs (dedupe_key)
    WHERE dedupe_key IS NOT NULL AND status IN ('pending', 'running');
"""


@dataclass
class Job:
    id: int
    kind: str
    payload: dict
    attempts: int


def init_queue(db_path: str | None = None) -> None:
    with store.connect(db_path) as connection:
        connection.executescript(SCHEMA)


def enqueue(
    kind: str,
    payload: dict,
    dedupe_key: str | None = None,
    db_path: str | None = None,
) -> int | None:
    """Adds a job. `dedupe_key` collapses duplicates: pushing three commits to a
    PR in quick succession should queue one review of the latest head, not three.
    Returns None when an identical job is already pending."""
    now = int(time.time())
    with store.connect(db_path) as connection:
        if dedupe_key:
            existing = connection.execute(
                "SELECT id FROM jobs WHERE dedupe_key = ? AND status IN ('pending','running')",
                (dedupe_key,),
            ).fetchone()
            if existing:
                # Supersede the older request - the newest head is what matters.
                connection.execute(
                    "UPDATE jobs SET payload = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(payload), now, existing["id"]),
                )
                return None
        cursor = connection.execute(
            """
            INSERT INTO jobs (kind, payload, status, created_at, updated_at, dedupe_key)
            VALUES (?, ?, 'pending', ?, ?, ?)
            """,
            (kind, json.dumps(payload), now, now, dedupe_key),
        )
        return cursor.lastrowid


def claim(db_path: str | None = None) -> Job | None:
    """Atomically takes one job. The UPDATE ... WHERE status='pending' is the
    lock, so two workers can never claim the same row."""
    now = int(time.time())
    with store.connect(db_path) as connection:
        # Reclaim anything a dead worker left behind.
        connection.execute(
            "UPDATE jobs SET status='pending', claimed_at=NULL, updated_at=? "
            "WHERE status='running' AND claimed_at < ?",
            (now, now - STALE_AFTER_SECONDS),
        )
        row = connection.execute(
            "SELECT id, kind, payload, attempts FROM jobs "
            "WHERE status='pending' AND run_after <= ? ORDER BY id LIMIT 1",
            (now,),
        ).fetchone()
        if row is None:
            return None

        updated = connection.execute(
            "UPDATE jobs SET status='running', attempts=attempts+1, claimed_at=?, updated_at=? "
            "WHERE id=? AND status='pending'",
            (now, now, row["id"]),
        )
        if updated.rowcount != 1:
            return None  # lost the race to another worker

        return Job(
            id=row["id"],
            kind=row["kind"],
            payload=json.loads(row["payload"]),
            attempts=row["attempts"] + 1,
        )


def complete(job_id: int, db_path: str | None = None) -> None:
    with store.connect(db_path) as connection:
        connection.execute(
            "UPDATE jobs SET status='done', dedupe_key=NULL, updated_at=? WHERE id=?",
            (int(time.time()), job_id),
        )


def fail(job_id: int, error: str, attempts: int, db_path: str | None = None) -> None:
    """Retries with backoff until MAX_ATTEMPTS, then parks the job as failed so
    it's visible rather than silently retried forever."""
    now = int(time.time())
    give_up = attempts >= MAX_ATTEMPTS
    with store.connect(db_path) as connection:
        connection.execute(
            "UPDATE jobs SET status=?, last_error=?, run_after=?, claimed_at=NULL, "
            "dedupe_key=CASE WHEN ? THEN NULL ELSE dedupe_key END, updated_at=? WHERE id=?",
            (
                "failed" if give_up else "pending",
                error[:1000],
                now + RETRY_BACKOFF_SECONDS * attempts,
                give_up,
                now,
                job_id,
            ),
        )


def stats(db_path: str | None = None) -> dict[str, int]:
    with store.connect(db_path) as connection:
        rows = connection.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
        return {row["status"]: row["n"] for row in rows}
