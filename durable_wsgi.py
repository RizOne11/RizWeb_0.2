from __future__ import annotations

from pathlib import Path

import app as legacy
from flask import jsonify

from puma_job_store import JobStore


_STORE = JobStore(legacy.JOBS_DIR)
_original_set_job = legacy.set_job
_original_get_job = legacy.get_job


def _restore_job_files(job_id: str, data: dict) -> None:
    if not _STORE.enabled:
        return
    filename = str(data.get("filename") or "").strip()
    if filename:
        _STORE.ensure_file(job_id, Path(filename).name)
    if data.get("status") == "done":
        for key, fallback in (
            ("xlsx_file", "PUMA_doPUMAgatel_market_report.xlsx"),
            ("classic_xlsx_file", "PUMA_classic_analytical_report.xlsx"),
        ):
            remote_name = Path(str(data.get(key) or fallback)).name
            _STORE.ensure_file(job_id, remote_name)


def set_job(job_id: str, **kwargs):
    _original_set_job(job_id, **kwargs)
    data = _original_get_job(job_id) or {}
    status = str(data.get("status") or "")

    if _STORE.enabled:
        # The original catalog is required for one-click reruns after a deploy.
        if status == "queued" and data.get("filename"):
            source = legacy.JOBS_DIR / job_id / Path(str(data["filename"])).name
            _STORE.upload_file(job_id, source)

        # Upload reports before publishing the final durable 'done' status.
        if status == "done":
            for key, fallback in (
                ("xlsx_file", "PUMA_doPUMAgatel_market_report.xlsx"),
                ("classic_xlsx_file", "PUMA_classic_analytical_report.xlsx"),
            ):
                path = Path(str(data.get(key) or (legacy.JOBS_DIR / job_id / fallback)))
                _STORE.upload_file(job_id, path, remote_name=path.name)

        _STORE.save_status(
            job_id,
            data,
            force=status in {"queued", "done", "error", "interrupted"},
        )


def get_job(job_id: str):
    data = _original_get_job(job_id)
    if data is None and _STORE.enabled:
        data = _STORE.load_status(job_id)
        if data is not None:
            with legacy._lock:
                legacy._jobs[job_id] = dict(data)
    if data is not None:
        _restore_job_files(job_id, data)
        return dict(data)
    return None


def _load_remote_jobs() -> None:
    if not _STORE.enabled:
        return
    for job_id in _STORE.list_remote_job_ids():
        data = _STORE.load_status(job_id)
        if not data:
            continue
        if data.get("status") in {"queued", "running"}:
            data["status"] = "interrupted"
            data["message"] = "Попередній процес перервався. Запусти аналіз повторно."
            _STORE.save_status(job_id, data, force=True)
        _original_set_job(job_id, **data)
        with legacy._lock:
            legacy._jobs[job_id] = dict(data)


# Route functions and workers resolve these globals from the legacy module at
# runtime, so replacing them here upgrades the existing app without duplicating it.
legacy.set_job = set_job
legacy.get_job = get_job
_load_remote_jobs()


@legacy.app.get("/api/storage")
def storage_status():
    return jsonify(
        {
            "mode": _STORE.mode,
            "durable": _STORE.enabled,
            "last_error": _STORE.last_error,
        }
    )


app = legacy.app
