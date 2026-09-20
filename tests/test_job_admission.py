import app as puma_app


def _reset(monkeypatch, tmp_path):
    monkeypatch.setattr(puma_app, "JOBS_DIR", tmp_path)
    monkeypatch.delenv("PUMA_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("PUMA_REQUIRE_AUTH", raising=False)
    monkeypatch.delenv("PUMA_JOB_STARTS_PER_MINUTE", raising=False)
    monkeypatch.delenv("PUMA_MAX_ACTIVE_JOBS", raising=False)
    monkeypatch.delenv("PUMA_MAX_OUTSTANDING_JOBS", raising=False)
    with puma_app._lock:
        puma_app._jobs.clear()
        puma_app._running_threads.clear()
        puma_app._submission_times.clear()


def _seed_job(tmp_path, job_id, *, status="queued", created_at=1):
    d = tmp_path / job_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "catalog.yml").write_text("offers: []\n", encoding="utf-8")
    puma_app.set_job(
        job_id,
        id=job_id,
        status=status,
        filename="catalog.yml",
        supplier="test",
        marketplaces=["prom"],
        limit=10,
        created_at=created_at,
    )


def test_active_job_limit_keeps_next_job_queued(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    monkeypatch.setenv("PUMA_MAX_ACTIVE_JOBS", "1")
    started = []

    class FakeThread:
        def __init__(self, *, target, args, daemon):
            self.args = args

        def start(self):
            started.append(self.args[0])

    monkeypatch.setattr(puma_app.threading, "Thread", FakeThread)
    _seed_job(tmp_path, "job-one", created_at=1)
    _seed_job(tmp_path, "job-two", created_at=2)

    assert puma_app._start_worker("job-one") is True
    assert puma_app._start_worker("job-two") is True
    assert started == ["job-one"]
    assert puma_app._active_job_count() == 1

    puma_app.set_job("job-one", status="done")
    with puma_app._lock:
        puma_app._running_threads.discard("job-one")
    puma_app._start_next_queued()

    assert started == ["job-one", "job-two"]
    assert puma_app._thread_alive("job-two")


def test_job_start_rate_limit_returns_429(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    monkeypatch.setenv("PUMA_JOB_STARTS_PER_MINUTE", "1")
    client = puma_app.app.test_client()

    first = client.post("/api/jobs/missing/resume")
    assert first.status_code == 404

    second = client.post("/api/jobs/missing/resume")
    assert second.status_code == 429
    payload = second.get_json()
    assert payload["error"] == "job_capacity_limited"
    assert int(second.headers["Retry-After"]) >= 1


def test_outstanding_job_cap_blocks_new_analysis(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    monkeypatch.setenv("PUMA_MAX_OUTSTANDING_JOBS", "1")
    _seed_job(tmp_path, "already-running", status="running")

    client = puma_app.app.test_client()
    response = client.post("/analyze")

    assert response.status_code == 429
    assert "черга" in response.get_data(as_text=True).casefold()


def test_limits_are_disabled_by_default_for_dev_and_tests(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    assert puma_app._max_active_jobs() == 0
    assert puma_app._max_outstanding_jobs() == 0
    assert puma_app._job_starts_per_minute() == 0
