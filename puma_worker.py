from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

os.environ.setdefault("PUMA_EXECUTION_MODE", "worker")

import app as legacy
import durable_wsgi as runtime


_STOP = threading.Event()


def _poll_seconds() -> float:
    try:
        return max(0.5, min(float(os.getenv("PUMA_WORKER_POLL_SECONDS", "2")), 30.0))
    except ValueError:
        return 2.0


def _request_local_cancel(job_id: str) -> None:
    with legacy._lock:
        legacy._cancel_events.setdefault(job_id, threading.Event()).set()
        if job_id in legacy._jobs:
            legacy._jobs[job_id]["status"] = "cancelling"


def sync_once() -> int:
    """Synchronize durable jobs into the worker process and start queued work."""
    store = runtime._STORE
    if not store.enabled:
        return 0

    seen = 0
    for job_id in store.list_remote_job_ids():
        data = store.load_remote_status(job_id)
        if not data:
            continue
        seen += 1
        status = str(data.get("status") or "")

        if legacy._thread_alive(job_id):
            if status == "cancelling":
                _request_local_cancel(job_id)
            continue

        if status == "cancelling":
            runtime.set_job(
                job_id,
                **data,
                status="cancelled",
                message="Аналіз скасовано до наступного worker кроку.",
                finished_at=time.time(),
            )
            continue

        if status not in {"queued", "running"}:
            with legacy._lock:
                legacy._jobs[job_id] = dict(data)
            continue

        filename = str(data.get("filename") or "").strip()
        input_path = store.ensure_file(job_id, Path(filename).name) if filename else None
        if data.get("resume_available"):
            store.ensure_file(job_id, "checkpoint.json")

        checkpoint = legacy.JOBS_DIR / job_id / "checkpoint.json"
        same_build = (data.get("engine_build") or legacy.ENGINE_BUILD) == legacy.ENGINE_BUILD
        if not input_path or not input_path.is_file():
            runtime.set_job(
                job_id,
                **data,
                status="error",
                message="Worker не зміг відновити вхідний файл з durable storage.",
                finished_at=time.time(),
            )
            continue
        if not same_build:
            runtime.set_job(
                job_id,
                **data,
                status="interrupted",
                message="Build змінився; автоматичне продовження цього job заблоковано.",
                resume_available=False,
            )
            continue

        queued = dict(data)
        queued["status"] = "queued"
        queued["resume_available"] = checkpoint.is_file()
        queued["message"] = (
            "Worker відновлює аналіз з checkpoint…"
            if checkpoint.is_file()
            else "Worker забрав задачу з черги…"
        )
        with legacy._lock:
            legacy._jobs[job_id] = queued
        runtime.set_job(job_id, **queued)
        legacy._start_worker(job_id)

    legacy._start_next_queued()
    return seen


def _shutdown(*_args) -> None:
    _STOP.set()
    with legacy._lock:
        events = list(legacy._cancel_events.values())
    for event in events:
        event.set()


def main() -> int:
    if legacy._execution_mode() != "worker":
        raise SystemExit("PUMA worker requires PUMA_EXECUTION_MODE=worker")
    if not runtime._STORE.enabled:
        raise SystemExit("PUMA worker requires durable PUMA_S3_* storage")

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    print(
        f"PUMA_WORKER started build={legacy.ENGINE_BUILD} poll={_poll_seconds()}s",
        flush=True,
    )

    while not _STOP.is_set():
        sync_once()
        _STOP.wait(_poll_seconds())

    print("PUMA_WORKER stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
