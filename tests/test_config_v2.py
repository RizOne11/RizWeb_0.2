import json

import app as puma_app
from puma_config import PRODUCTION_MARKETPLACES, load_config, production_marketplace_ids, ui_config


EXPECTED_IDS = ("prom", "epicentr", "hotline", "web_shops")


def test_config_v2_preserves_legacy_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "marketplaces": [{"name": "Legacy Rozetka", "domain": "rozetka.com.ua"}],
                "match_threshold": 72,
                "app_name": "PUMA Test",
            }
        ),
        encoding="utf-8",
    )

    cfg = load_config(path)

    assert cfg["schema_version"] == 2
    assert cfg["marketplaces"][0]["domain"] == "rozetka.com.ua"
    assert cfg["match_threshold"] == 72
    assert tuple(x["id"] for x in cfg["production"]["marketplaces"]) == EXPECTED_IDS


def test_config_v2_normalizes_partial_production_sources(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "production": {
                    "marketplaces": [
                        {"id": "hotline", "name": "HOTLINE CUSTOM"},
                        {"id": "unknown", "name": "Do not include"},
                        {"id": "hotline", "name": "Duplicate"},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    cfg = load_config(path)
    sources = cfg["production"]["marketplaces"]

    assert tuple(x["id"] for x in sources) == ("hotline", "prom", "epicentr", "web_shops")
    assert sources[0]["name"] == "HOTLINE CUSTOM"
    assert "unknown" not in {x["id"] for x in sources}


def test_repository_config_declares_only_current_production_source_ids():
    assert production_marketplace_ids() == EXPECTED_IDS
    assert tuple(x["id"] for x in PRODUCTION_MARKETPLACES) == EXPECTED_IDS


def test_ui_config_uses_config_v2_production_sources():
    cfg = ui_config()
    assert cfg["app_version"] == "v1.3"
    assert tuple(x["id"] for x in cfg["marketplaces"]) == EXPECTED_IDS


def test_analysis_page_renders_configured_production_sources(monkeypatch):
    monkeypatch.delenv("PUMA_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("PUMA_REQUIRE_AUTH", raising=False)
    client = puma_app.app.test_client()

    response = client.get("/analysis")

    assert response.status_code == 200
    text = response.get_data(as_text=True)
    for source_id in EXPECTED_IDS:
        assert f'value="{source_id}"' in text
    assert 'value="rozetka"' not in text
    assert 'value="allo"' not in text
    assert 'value="comfy"' not in text


def test_legacy_main_entrypoint_remains_importable():
    import main

    assert callable(main.main)
    assert main.main.__module__ == "legacy.priceintel_cli"
