import asyncio
import json

import app as puma_app
from puma_scouts import production
from puma_scouts.models import ScanHealth


def _catalog(path):
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<yml_catalog>
  <shop>
    <offers>
      <offer id="1"><name>Test Product One</name><vendorCode>A1</vendorCode></offer>
      <offer id="2"><name>Test Product Two</name><vendorCode>A2</vendorCode></offer>
      <offer id="3"><name>Test Product Three</name><vendorCode>A3</vendorCode></offer>
    </offers>
  </shop>
</yml_catalog>
""",
        encoding="utf-8",
    )


def test_production_checkpoint_resumes_only_unfinished_products(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.yml"
    output = tmp_path / "report.xlsx"
    checkpoint = tmp_path / "checkpoint.json"
    _catalog(catalog)

    calls = []

    async def first_scan(mission, selected=None):
        calls.append(mission.article)
        if mission.article == "A2":
            raise RuntimeError("simulated worker death")
        return [], {"prom": {"health": ScanHealth.NOT_FOUND.value, "errors": []}}

    monkeypatch.setattr(production, "PRODUCT_CONCURRENCY", 1)
    monkeypatch.setattr(production, "scan_detailed", first_scan)

    try:
        asyncio.run(
            production.run(
                str(catalog),
                str(output),
                checkpoint_path=str(checkpoint),
                checkpoint_token="build-one",
            )
        )
    except RuntimeError as exc:
        assert "simulated worker death" in str(exc)
    else:
        raise AssertionError("first run should simulate interruption")

    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["checkpoint_token"] == "build-one"
    assert saved["completed_indexes"] == [0]
    assert calls == ["A1", "A2"]

    resumed_calls = []

    async def resumed_scan(mission, selected=None):
        resumed_calls.append(mission.article)
        return [], {"prom": {"health": ScanHealth.NOT_FOUND.value, "errors": []}}

    monkeypatch.setattr(production, "scan_detailed", resumed_scan)
    summary = asyncio.run(
        production.run(
            str(catalog),
            str(output),
            checkpoint_path=str(checkpoint),
            checkpoint_token="build-one",
        )
    )

    assert resumed_calls == ["A2", "A3"]
    assert summary["products"] == 3
    assert not checkpoint.exists()


def test_checkpoint_from_different_build_is_not_reused(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.yml"
    output = tmp_path / "report.xlsx"
    checkpoint = tmp_path / "checkpoint.json"
    _catalog(catalog)

    checkpoint.write_text(
        json.dumps(
            {
                "version": 1,
                "checkpoint_token": "old-build",
                "articles": ["A1", "A2", "A3"],
                "completed": {
                    "0": {"article": "A1", "found": [], "diagnostics": {}}
                },
            }
        ),
        encoding="utf-8",
    )

    calls = []

    async def scan(mission, selected=None):
        calls.append(mission.article)
        return [], {}

    monkeypatch.setattr(production, "PRODUCT_CONCURRENCY", 1)
    monkeypatch.setattr(production, "scan_detailed", scan)

    asyncio.run(
        production.run(
            str(catalog),
            str(output),
            checkpoint_path=str(checkpoint),
            checkpoint_token="new-build",
        )
    )
    assert calls == ["A1", "A2", "A3"]


def test_resume_endpoint_restarts_interrupted_job(tmp_path, monkeypatch):
    monkeypatch.setattr(puma_app, "JOBS_DIR", tmp_path)
    started = []
    monkeypatch.setattr(puma_app, "_start_worker", lambda job_id: started.append(job_id) or True)

    with puma_app._lock:
        puma_app._jobs.clear()

    job_id = "resume123"
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "catalog.yml").write_text("<yml_catalog/>", encoding="utf-8")
    (job_dir / "checkpoint.json").write_text("{}", encoding="utf-8")

    puma_app.set_job(
        job_id,
        id=job_id,
        status="interrupted",
        filename="catalog.yml",
        supplier="test",
        marketplaces=["prom"],
        limit=100,
        engine_build=puma_app.ENGINE_BUILD,
        resume_available=True,
    )

    client = puma_app.app.test_client()
    response = client.post(f"/api/jobs/{job_id}/resume")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert started == [job_id]
    current = puma_app.get_job(job_id)
    assert current["status"] == "queued"
    assert current["resume_available"] is True
