import asyncio
import json

import pytest

import app as puma_app
from puma_scouts import production


def _reset_app(monkeypatch, tmp_path):
    monkeypatch.setattr(puma_app, "JOBS_DIR", tmp_path)
    monkeypatch.delenv("PUMA_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("PUMA_REQUIRE_AUTH", raising=False)
    monkeypatch.delenv("PUMA_JOB_STARTS_PER_MINUTE", raising=False)
    monkeypatch.delenv("PUMA_MAX_OUTSTANDING_JOBS", raising=False)
    with puma_app._lock:
        puma_app._jobs.clear()
        puma_app._running_threads.clear()
        puma_app._cancel_events.clear()
        puma_app._submission_times.clear()


def _seed_job(tmp_path, job_id, *, status="queued"):
    d = tmp_path / job_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "catalog.yml").write_text("<yml_catalog/>", encoding="utf-8")
    puma_app.set_job(
        job_id,
        id=job_id,
        status=status,
        filename="catalog.yml",
        supplier="test",
        marketplaces=["prom"],
        limit=10,
        created_at=1,
        engine_build=puma_app.ENGINE_BUILD,
    )


def test_queued_job_cancels_immediately(monkeypatch, tmp_path):
    _reset_app(monkeypatch, tmp_path)
    _seed_job(tmp_path, "queued-cancel", status="queued")

    client = puma_app.app.test_client()
    response = client.post("/api/jobs/queued-cancel/cancel")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "cancelled"
    assert payload["immediate"] is True
    assert puma_app.get_job("queued-cancel")["status"] == "cancelled"
    assert puma_app._cancel_events["queued-cancel"].is_set()


def test_running_job_enters_cancelling_and_sets_event(monkeypatch, tmp_path):
    _reset_app(monkeypatch, tmp_path)
    _seed_job(tmp_path, "running-cancel", status="running")
    with puma_app._lock:
        puma_app._running_threads.add("running-cancel")

    client = puma_app.app.test_client()
    response = client.post("/api/jobs/running-cancel/cancel")

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["status"] == "cancelling"
    assert payload["immediate"] is False
    assert puma_app.get_job("running-cancel")["status"] == "cancelling"
    assert puma_app._cancel_events["running-cancel"].is_set()

    with puma_app._lock:
        puma_app._running_threads.discard("running-cancel")


def test_worker_records_cancelled_instead_of_error(monkeypatch, tmp_path):
    _reset_app(monkeypatch, tmp_path)
    _seed_job(tmp_path, "worker-cancel", status="queued")

    def cancelled_run(*args, **kwargs):
        raise production.RunCancelled("stop")

    monkeypatch.setattr(puma_app, "run_sync", cancelled_run)
    puma_app.worker(
        "worker-cancel",
        tmp_path / "worker-cancel" / "catalog.yml",
        10,
        ["prom"],
        "test",
    )

    job = puma_app.get_job("worker-cancel")
    assert job["status"] == "cancelled"
    assert "скасовано" in job["message"].casefold()


def test_engine_cancellation_preserves_completed_checkpoint(monkeypatch, tmp_path):
    catalog = tmp_path / "catalog.csv"
    catalog.write_text(
        "article;name\nA1;Test Product One\nA2;Test Product Two\nA3;Test Product Three\n",
        encoding="utf-8",
    )
    output = tmp_path / "report.xlsx"
    checkpoint = tmp_path / "checkpoint.json"
    cancelled = {"value": False}
    calls = []

    async def scan(mission, selected=None, scout_pool=None):
        calls.append(mission.article)
        if mission.article == "A1":
            cancelled["value"] = True
        return [], {}

    monkeypatch.setattr(production, "PRODUCT_CONCURRENCY", 1)
    monkeypatch.setattr(production, "scan_detailed", scan)

    with pytest.raises(production.RunCancelled):
        asyncio.run(
            production.run(
                str(catalog),
                str(output),
                checkpoint_path=str(checkpoint),
                checkpoint_token="cancel-build",
                cancel_cb=lambda: cancelled["value"],
            )
        )

    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["completed_indexes"] == [0]
    assert calls == ["A1"]
