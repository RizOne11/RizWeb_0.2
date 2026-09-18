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
    if data.get("resume_available"):
        _STORE.ensure_file(job_id, "checkpoint.json")
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

        # Mirror the per-product checkpoint before the running status is synced.
        # A replacement instance can then continue the same job instead of
        # throwing away already completed products.
        if status == "running":
            checkpoint = legacy.JOBS_DIR / job_id / "checkpoint.json"
            if checkpoint.is_file():
                _STORE.upload_file(job_id, checkpoint, remote_name="checkpoint.json")

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
    auto_resume: list[str] = []
    for job_id in _STORE.list_remote_job_ids():
        data = _STORE.load_status(job_id)
        if not data:
            continue

        status = str(data.get("status") or "")
        if status in {"queued", "running"}:
            filename = str(data.get("filename") or "").strip()
            input_path = _STORE.ensure_file(job_id, Path(filename).name) if filename else None
            if data.get("resume_available"):
                _STORE.ensure_file(job_id, "checkpoint.json")
            checkpoint = legacy.JOBS_DIR / job_id / "checkpoint.json"
            same_build = (data.get("engine_build") or "legacy") == legacy.ENGINE_BUILD

            if same_build and input_path and input_path.is_file():
                data["status"] = "queued"
                data["message"] = (
                    "Автоматично відновлюємо аналіз з контрольної точки…"
                    if checkpoint.is_file()
                    else "Автоматично перезапускаємо незавершений аналіз…"
                )
                data["resume_available"] = checkpoint.is_file()
                data["auto_resume_count"] = int(data.get("auto_resume_count") or 0) + 1
                _STORE.save_status(job_id, data, force=True)
                auto_resume.append(job_id)
            else:
                data["status"] = "interrupted"
                data["resume_available"] = bool(checkpoint.is_file() and same_build)
                data["message"] = (
                    "Попередній процес перервався. Можна продовжити з останньої контрольної точки."
                    if data["resume_available"]
                    else "Попередній процес перервався. Запусти аналіз повторно."
                )
                _STORE.save_status(job_id, data, force=True)

        _original_set_job(job_id, **data)
        with legacy._lock:
            legacy._jobs[job_id] = dict(data)

    for job_id in auto_resume:
        legacy._start_worker(job_id)

def _storage_is_healthy() -> bool:
    """Verify that configured S3 credentials can at least list the job prefix.

    This intentionally avoids logging endpoint, bucket or credential details.
    Actual job writes are still verified by the normal upload/status path.
    """
    if not _STORE.enabled:
        return False
    _STORE.list_remote_job_ids()
    return _STORE.last_error is None


# Route functions and workers resolve these globals from the legacy module at
# runtime, so replacing them here upgrades the existing app without duplicating it.
legacy.set_job = set_job
legacy.get_job = get_job
_load_remote_jobs()

_startup_storage_healthy = _storage_is_healthy()
print(
    f"PUMA_STORAGE mode={_STORE.mode} durable={str(_STORE.enabled and _startup_storage_healthy).lower()}",
    flush=True,
)


@legacy.app.get("/api/storage")
def storage_status():
    healthy = _storage_is_healthy()
    return jsonify({"mode": _STORE.mode, "durable": bool(_STORE.enabled and healthy)})


app = legacy.app
