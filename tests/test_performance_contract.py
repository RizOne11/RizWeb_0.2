import asyncio

from puma_scouts import production


def _catalog(path, count=8):
    offers = "\n".join(
        f'<offer id="{i}"><name>Perf Product {i}</name><vendorCode>P{i}</vendorCode></offer>'
        for i in range(1, count + 1)
    )
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<yml_catalog><shop><offers>{offers}</offers></shop></yml_catalog>
""",
        encoding="utf-8",
    )


def test_product_parallelism_contract_uses_configured_concurrency(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.yml"
    output = tmp_path / "report.xlsx"
    _catalog(catalog, 8)

    active = 0
    peak = 0

    async def fake_scan(mission, selected=None, scout_pool=None):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return [], {}

    monkeypatch.setattr(production, "PRODUCT_CONCURRENCY", 4)
    monkeypatch.setattr(production, "scan_detailed", fake_scan)
    monkeypatch.setattr(production, "scouts", lambda selected=None: [object()])

    summary = asyncio.run(production.run(str(catalog), str(output)))

    assert peak == 4
    assert summary["product_concurrency"] == 4
    assert summary["products"] == 8
