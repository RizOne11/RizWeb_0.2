import asyncio
from decimal import Decimal

from puma_scouts import production
from puma_scouts.models import Marketplace
from puma_scouts.scouts.base import MarketplaceScout, repair_discovery_scope


class _DummyScout(MarketplaceScout):
    marketplace = Marketplace.PROM

    async def generate_queries(self, mission):
        return ["q1", "q2", "q3"]

    async def discover(self, mission, query):
        return []

    async def scan(self, mission):
        raise NotImplementedError


def _catalog(path):
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<yml_catalog><shop><offers>
<offer id="1"><name>Honda EU35i</name><vendorCode>SKU-1</vendorCode></offer>
</offers></shop></yml_catalog>
""",
        encoding="utf-8",
    )


def _row(mission, source="prom"):
    return {
        "article": mission.article,
        "name": mission.source_data.get("name", ""),
        "brand": mission.source_data.get("brand", ""),
        "model": mission.source_data.get("model", ""),
        "own_price": mission.source_data.get("own_price", ""),
        "source": source,
        "price": 1000.0,
        "currency": "UAH",
        "availability": "in stock",
        "found_title": mission.source_data.get("name", ""),
        "url": "https://prom.ua/p-test.html",
        "match": 0.99,
        "identity_confidence": "CONFIRMED",
        "domain": "prom.ua",
        "health": "FOUND",
    }


def test_repair_scope_is_task_local_and_limits_queries(monkeypatch):
    scout = _DummyScout()
    monkeypatch.setenv("PUMA_REFRESH_ONLY", "1")
    monkeypatch.delenv("PUMA_REPAIR_QUERY_LIMIT", raising=False)

    assert scout.refresh_only() is True
    assert scout.bound_queries(["a", "b", "c"]) == ["a", "b", "c"]
    with repair_discovery_scope(True):
        assert scout.repair_mode() is True
        assert scout.refresh_only() is False
        assert scout.bound_queries(["a", "b", "c"]) == ["a"]
    assert scout.refresh_only() is True


def test_refresh_repairs_only_known_discovery_sources(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.yml"
    output = tmp_path / "report.xlsx"
    _catalog(catalog)
    calls = []

    async def fake_scan(mission, selected=None, scout_pool=None, force_discovery=False):
        calls.append((tuple(selected or ()), force_discovery))
        if force_discovery:
            return [_row(mission)], {
                "prom": {
                    "health": "FOUND",
                    "elapsed_seconds": 0.1,
                    "errors": [],
                    "metrics": {},
                }
            }
        return [], {
            "prom": {
                "health": "NOT_FOUND",
                "elapsed_seconds": 0.1,
                "errors": ["identity-refresh dead"],
                "metrics": {
                    "identity_urls_loaded": 1,
                    "identity_urls_attempted": 1,
                    "repair_required": True,
                },
            }
        }

    monkeypatch.setenv("PUMA_REFRESH_ONLY", "1")
    monkeypatch.setenv("PUMA_REFRESH_REPAIR_ENABLED", "1")
    monkeypatch.setattr(production, "scan_detailed", fake_scan)
    monkeypatch.setattr(production, "scouts", lambda selected=None: [])
    monkeypatch.setattr(production, "load_discovery_sources", lambda mission: ["prom"])
    monkeypatch.setattr(production, "PRODUCT_CONCURRENCY", 1)

    summary = asyncio.run(production.run(str(catalog), str(output)))

    assert calls == [((), False), (("prom",), True)]
    assert summary["found_products"] == 1
    assert summary["repair_products_attempted"] == 1
    assert summary["repair_products_rescued"] == 1


def test_refresh_does_not_repair_without_prior_discovery_state(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.yml"
    output = tmp_path / "report.xlsx"
    _catalog(catalog)
    calls = []

    async def fake_scan(mission, selected=None, scout_pool=None, force_discovery=False):
        calls.append(force_discovery)
        return [], {}

    monkeypatch.setenv("PUMA_REFRESH_ONLY", "1")
    monkeypatch.setenv("PUMA_REFRESH_REPAIR_ENABLED", "1")
    monkeypatch.setattr(production, "scan_detailed", fake_scan)
    monkeypatch.setattr(production, "scouts", lambda selected=None: [])
    monkeypatch.setattr(production, "load_discovery_sources", lambda mission: None)
    monkeypatch.setattr(production, "PRODUCT_CONCURRENCY", 1)

    summary = asyncio.run(production.run(str(catalog), str(output)))

    assert calls == [False]
    assert summary["found_products"] == 0
    assert summary["repair_products_attempted"] == 0


def test_refresh_repairs_missing_prior_source_even_when_product_found_elsewhere(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.yml"
    output = tmp_path / "report.xlsx"
    _catalog(catalog)
    calls = []

    async def fake_scan(mission, selected=None, scout_pool=None, force_discovery=False):
        calls.append((tuple(selected or ()), force_discovery))
        if force_discovery:
            return [_row(mission, "epicentr")], {
                "epicentr": {
                    "health": "FOUND",
                    "elapsed_seconds": 0.1,
                    "errors": [],
                    "metrics": {},
                }
            }
        return [_row(mission, "prom")], {
            "prom": {
                "health": "FOUND",
                "elapsed_seconds": 0.1,
                "errors": [],
                "metrics": {"identity_refresh_hit": True},
            },
            "epicentr": {
                "health": "NOT_FOUND",
                "elapsed_seconds": 0.1,
                "errors": [],
                "metrics": {"discovery_gap": True},
            },
        }

    monkeypatch.setenv("PUMA_REFRESH_ONLY", "1")
    monkeypatch.setenv("PUMA_REFRESH_REPAIR_ENABLED", "1")
    monkeypatch.setattr(production, "scan_detailed", fake_scan)
    monkeypatch.setattr(production, "scouts", lambda selected=None: [])
    monkeypatch.setattr(production, "load_discovery_sources", lambda mission: ["prom", "epicentr"])
    monkeypatch.setattr(production, "PRODUCT_CONCURRENCY", 1)

    summary = asyncio.run(production.run(str(catalog), str(output)))

    assert calls == [((), False), (("epicentr",), True)]
    assert summary["found_products"] == 1
    product = summary["product_results"][0]
    assert set(x["source"] for x in product["offers_detail"]) == {"prom", "epicentr"}
    assert summary["repair_products_attempted"] == 1
    assert summary["repair_products_rescued"] == 1
