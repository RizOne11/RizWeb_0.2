import threading
from pathlib import Path
from types import SimpleNamespace

import app as puma_app
import puma_worker


def _reset_app(monkeypatch, tmp_path):
    monkeypatch.setattr(puma_app, "JOBS_DIR", tmp_path)
    monkeypatch.delenv("PUMA_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("PUMA_REQUIRE_AUTH", raising=False)
    with puma_app._lock:
        puma_app._jobs.clear()
        puma_app._running_threads.clear()
        puma_app._cancel_events.clear()


def test_web_execution_mode_enqueues_without_starting_local_thread(monkeypatch, tmp_path):
    _reset_app(monkeypatch, tmp_path)
    monkeypatch.setenv("PUMA_EXECUTION_MODE", "web")
    started = []

    class FakeThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            started.append(True)

    monkeypatch.setattr(puma_app.threading, "Thread", FakeThread)
    job_id = "web-only-job"
    d = tmp_path / job_id
    d.mkdir(parents=True)
    (d / "catalog.yml").write_text("<yml_catalog/>", encoding="utf-8")
    puma_app.set_job(
        job_id,
        id=job_id,
        status="queued",
        filename="catalog.yml",
        supplier="test",
        marketplaces=["prom"],
        limit=10,
        created_at=1,
    )

    assert puma_app._execution_mode() == "web"
    assert puma_app._start_worker(job_id) is True
    assert started == []
    assert not puma_app._thread_alive(job_id)


class FakeStore:
    def __init__(self, tmp_path, payload):
        self.enabled = True
        self.tmp_path = Path(tmp_path)
        self.payload = payload

    def list_remote_job_ids(self):
        return list(self.payload)

    def load_remote_status(self, job_id):
        return dict(self.payload[job_id])

    def ensure_file(self, job_id, filename):
        path = self.tmp_path / job_id / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if filename != "checkpoint.json":
            path.write_text("catalog", encoding="utf-8")
        return path


class FakeLegacy:
    def __init__(self, tmp_path):
        self._lock = threading.Lock()
        self._jobs = {}
        self._cancel_events = {}
        self._running = set()
        self.JOBS_DIR = Path(tmp_path)
        self.ENGINE_BUILD = "build-1"
        self.started = []
        self.next_calls = 0

    def _thread_alive(self, job_id):
        return job_id in self._running

    def _start_worker(self, job_id):
        self.started.append(job_id)
        return True

    def _start_next_queued(self):
        self.next_calls += 1


class FakeRuntime:
    def __init__(self, store):
        self._STORE = store
        self.saved = []

    def set_job(self, job_id, **data):
        self.saved.append((job_id, dict(data)))


def test_worker_sync_claims_durable_queued_job(tmp_path):
    payload = {
        "job-1": {
            "id": "job-1",
            "status": "queued",
            "filename": "catalog.yml",
            "supplier": "test",
            "marketplaces": ["prom"],
            "limit": 10,
            "engine_build": "build-1",
        }
    }
    store = FakeStore(tmp_path, payload)
    legacy = FakeLegacy(tmp_path)
    runtime = FakeRuntime(store)

    assert puma_worker.sync_once(runtime=runtime, legacy=legacy) == 1
    assert legacy.started == ["job-1"]
    assert legacy._jobs["job-1"]["status"] == "queued"
    assert runtime.saved[-1][1]["status"] == "queued"
    assert legacy.next_calls == 1


def test_worker_sync_forwards_remote_cancel_to_running_job(tmp_path):
    payload = {
        "job-2": {
            "id": "job-2",
            "status": "cancelling",
            "filename": "catalog.yml",
            "engine_build": "build-1",
        }
    }
    store = FakeStore(tmp_path, payload)
    legacy = FakeLegacy(tmp_path)
    legacy._running.add("job-2")
    legacy._jobs["job-2"] = dict(payload["job-2"], status="running")
    runtime = FakeRuntime(store)

    puma_worker.sync_once(runtime=runtime, legacy=legacy)

    assert legacy._cancel_events["job-2"].is_set()
    assert legacy._jobs["job-2"]["status"] == "cancelling"
    assert legacy.started == []


def test_worker_refuses_resume_from_different_build(tmp_path):
    payload = {
        "job-old": {
            "id": "job-old",
            "status": "queued",
            "filename": "catalog.yml",
            "engine_build": "old-build",
        }
    }
    store = FakeStore(tmp_path, payload)
    legacy = FakeLegacy(tmp_path)
    runtime = FakeRuntime(store)

    puma_worker.sync_once(runtime=runtime, legacy=legacy)

    assert legacy.started == []
    assert runtime.saved[-1][1]["status"] == "interrupted"
    assert runtime.saved[-1][1]["resume_available"] is False
