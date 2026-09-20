"""Drains the job queue.

Runs either as its own process (`python service/worker.py`, the right shape when
you scale reviews independently of the web tier) or inside the API process when
PARACHECK_INLINE_WORKER=1, which keeps a single-container deploy to one thing to
run. Either way the work is in the database, so a restart resumes rather than
drops.

Review jobs are blocking and CPU/IO heavy - dependency installs, solc, Slither -
so they run in a thread, never on the event loop.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal

import jobs
import jobqueue as job_queue
import store

LOG = logging.getLogger("paracheck.worker")

IDLE_SLEEP_SECONDS = float(os.environ.get("PARACHECK_WORKER_IDLE_SECONDS", "5"))
# A hung forge/npm install must not pin a worker forever; the queue reclaims the
# job after STALE_AFTER_SECONDS but the thread would leak without this.
JOB_TIMEOUT_SECONDS = float(os.environ.get("PARACHECK_JOB_TIMEOUT_SECONDS", "1500"))

HANDLERS = {
    "review_pull_request": jobs.run_review_job,
    "scan_repository": jobs.run_repository_scan,
}


async def run_job(job: job_queue.Job) -> None:
    handler = HANDLERS.get(job.kind)
    if handler is None:
        job_queue.fail(job.id, f"unknown job kind: {job.kind}", job_queue.MAX_ATTEMPTS)
        return

    # Handlers may be async (network-bound) or plain blocking functions; a
    # blocking one must not run on this loop, which the API may share.
    if asyncio.iscoroutinefunction(handler):
        coroutine = handler(**job.payload)
    else:
        coroutine = asyncio.to_thread(handler, **job.payload)

    try:
        await asyncio.wait_for(coroutine, timeout=JOB_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        LOG.warning("job %s timed out after %ss", job.id, JOB_TIMEOUT_SECONDS)
        job_queue.fail(job.id, f"timed out after {JOB_TIMEOUT_SECONDS}s", job.attempts)
    except Exception as exc:  # noqa: BLE001 - one bad job must not kill the worker
        LOG.exception("job %s failed", job.id)
        job_queue.fail(job.id, f"{type(exc).__name__}: {exc}", job.attempts)
    else:
        job_queue.complete(job.id)


async def worker_loop(stop: asyncio.Event) -> None:
    LOG.info("worker started")
    while not stop.is_set():
        try:
            job = await asyncio.to_thread(job_queue.claim)
        except Exception:  # noqa: BLE001 - a transient DB error shouldn't end the worker
            LOG.exception("could not claim a job")
            job = None

        if job is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=IDLE_SLEEP_SECONDS)
            except asyncio.TimeoutError:
                pass
            continue

        LOG.info("running job %s (%s, attempt %s)", job.id, job.kind, job.attempts)
        await run_job(job)
    LOG.info("worker stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    store.init_db()
    job_queue.init_queue()

    async def run() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            # Finish the job in hand instead of dying mid-review on a deploy.
            loop.add_signal_handler(sig, stop.set)
        await worker_loop(stop)

    asyncio.run(run())


if __name__ == "__main__":
    main()
