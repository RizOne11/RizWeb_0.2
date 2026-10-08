import importlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from flask import Flask

import app as legacy
from puma_job_store import JobStore


class S3:
    def __init__(self, fail_suffix=None, fail_list=False):
        self.objects = {}
        self.fail_suffix = fail_suffix
        self.fail_list = fail_list

    def put_object(self, Bucket, Key, Body, **kwargs):
        if self.fail_suffix and Key.endswith(self.fail_suffix):
            raise RuntimeError("provider error with sensitive details")
        self.objects[Key] = Body.read() if hasattr(Body, "read") else bytes(Body)

    def list_objects_v2(self, **kwargs):
        if self.fail_list:
            raise RuntimeError("provider error with sensitive details")
        return {"Contents": [], "IsTruncated": False}


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    # Importing the WSGI adapter installs hooks. Restore the application globals
    # after this test so the original app tests keep their local-only runtime.
    monkeypatch.setattr(legacy, "set_job", legacy.set_job)
    monkeypatch.setattr(legacy, "get_job", legacy.get_job)
    monkeypatch.setattr(legacy, "_outstanding_job_count", legacy._outstanding_job_count)
    monkeypatch.setattr(legacy, "_jobs", {})
    monkeypatch.setattr(legacy, "JOBS_DIR", tmp_path)
    monkeypatch.setattr(legacy, "app", Flask("durable-runtime-test"))
    monkeypatch.setenv("PUMA_EXECUTION_MODE", "combined")
    d = importlib.import_module("durable_wsgi")
    env = {
        "PUMA_S3_BUCKET": "test", "PUMA_S3_ENDPOINT": "https://example.invalid",
        "PUMA_S3_ACCESS_KEY_ID": "test", "PUMA_S3_SECRET_ACCESS_KEY": "test",
        "PUMA_S3_STATUS_SYNC_SECONDS": "0",
    }
    client = S3()
    monkeypatch.setattr(d, "_STORE", JobStore(tmp_path, client=client, env=env))
    return d, client, tmp_path


@pytest.mark.parametrize("transition,filename", [
    ("queued", "catalog.yml"), ("running", "checkpoint.json"),
    ("cancelled", "checkpoint.json"), ("done", "report.xlsx"),
])
def test_failed_file_upload_does_not_publish_transition(runtime, transition, filename):
    d, client, base = runtime
    directory = base / "job"
    directory.mkdir()
    path = directory / filename
    path.write_bytes(b"job data")
    client.fail_suffix = filename
    with pytest.raises(d.DurableStorageError):
        d.set_job("job", id="job", status=transition, filename="catalog.yml",
                  xlsx_file=str(path), classic_xlsx_file=str(path))
    assert d._original_get_job("job")["status"] == "error"
    assert json.loads(client.objects["jobs/job/status.json"])["status"] == "error"
    assert "sensitive" not in d._original_get_job("job")["message"]


def test_done_published_only_after_both_reports(runtime):
    d, client, base = runtime
    directory = base / "job"
    directory.mkdir()
    report, classic = directory / "report.xlsx", directory / "classic.xlsx"
    report.write_bytes(b"report")
    classic.write_bytes(b"classic")
    d.set_job("job", id="job", status="done", xlsx_file=str(report), classic_xlsx_file=str(classic))
    assert list(client.objects) == ["jobs/job/report.xlsx", "jobs/job/classic.xlsx", "jobs/job/status.json"]
    assert d._original_get_job("job")["status"] == "done"


def test_failed_status_upload_cannot_leave_local_done(runtime):
    d, client, base = runtime
    directory = base / "job"
    directory.mkdir()
    report = directory / "report.xlsx"
    report.write_bytes(b"report")
    client.fail_suffix = "status.json"
    with pytest.raises(d.DurableStorageError):
        d.set_job("job", id="job", status="done", xlsx_file=str(report), classic_xlsx_file=str(report))
    assert d._original_get_job("job")["status"] == "error"
    assert "jobs/job/status.json" not in client.objects


def test_worker_readiness_detects_swallowed_storage_errors(runtime, monkeypatch):
    d, client, _ = runtime
    s = importlib.import_module("puma_worker_service")
    s._STOP.clear()
    monkeypatch.setattr(s, "_LAST_SYNC", {"at": 0.0, "seen": 0, "error": None})
    assert not s.health_payload()["ready"]
    client.fail_list = True
    monkeypatch.setattr(s._STOP, "wait", lambda seconds: s._STOP.set())
    try:
        s.worker_loop()
        assert s._LAST_SYNC["error"] == "RuntimeError"
        s._STOP.clear()
        assert not s.health_payload()["ready"]
        client.fail_list = False
        s.worker_loop()
        s._STOP.clear()
        assert s.health_payload()["ready"]
        s._LAST_SYNC["at"] = time.time() - 120
        assert not s.health_payload()["ready"]
    finally:
        s._STOP.clear()


def test_worker_service_idle_health_and_sigterm():
    env = {key: value for key, value in os.environ.items() if not key.startswith("PUMA_S3_")}
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env.update(PORT=str(port), PUMA_EXECUTION_MODE="worker")
    proc = subprocess.Popen([sys.executable, "puma_worker_service.py"],
                            cwd=Path(__file__).resolve().parents[1], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 8
        while True:
            try:
                with opener.open(f"http://127.0.0.1:{port}/healthz", timeout=1) as response:
                    payload = json.load(response)
                break
            except OSError:
                if proc.poll() is not None or time.monotonic() > deadline:
                    pytest.fail("worker service failed to start")
                time.sleep(0.05)
        assert payload["ready"] is False
        assert payload["durable_storage"] is False
        proc.terminate()
        assert proc.wait(timeout=3) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
