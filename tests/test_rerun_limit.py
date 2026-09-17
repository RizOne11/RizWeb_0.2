import app as puma_app


def test_rerun_can_override_product_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(puma_app, "JOBS_DIR", tmp_path)
    monkeypatch.setattr(puma_app, "_start_worker", lambda job_id: True)
    with puma_app._lock:
        puma_app._jobs.clear()

    old = "oldjob123"
    d = tmp_path / old
    d.mkdir(parents=True)
    src = d / "catalog.yml"
    src.write_text("offers: []\n", encoding="utf-8")
    puma_app.set_job(
        old,
        id=old,
        status="done",
        filename=src.name,
        supplier="test",
        marketplaces=["prom", "epicentr", "hotline", "web_shops"],
        limit=15,
        fingerprint="baseline",
    )

    client = puma_app.app.test_client()
    response = client.post(f"/api/jobs/{old}/rerun?limit=100")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["reused"] is False

    created = puma_app.get_job(payload["job_id"])
    assert created["limit"] == 100
    assert created["parent_job"] == old
