from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


BASE = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE / "config.json"

PRODUCTION_MARKETPLACES = [
    {"id": "prom", "name": "Prom", "domain": "prom.ua"},
    {"id": "epicentr", "name": "Epicentr", "domain": "epicentrk.ua"},
    {"id": "hotline", "name": "Hotline", "domain": "hotline.ua"},
    {"id": "web_shops", "name": "WEB_SHOPS", "domain": None},
]


def _production_defaults() -> dict[str, Any]:
    return {
        "marketplaces": deepcopy(PRODUCTION_MARKETPLACES),
        "matcher_frozen": True,
        "currency": "UAH",
        "market_scope": "UA",
    }


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load Config v2 while preserving every legacy top-level key.

    Legacy PriceIntel code still reads its historic top-level marketplace and
    provider keys. Config v2 therefore adds a dedicated production section
    instead of repurposing or removing those keys.
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    data: dict[str, Any] = {}
    if config_path.is_file():
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("PUMA config root must be a JSON object")
        data.update(loaded)

    data["schema_version"] = max(2, int(data.get("schema_version") or 0))
    production = data.get("production")
    if not isinstance(production, dict):
        production = {}
    merged_production = _production_defaults()
    merged_production.update(production)

    marketplaces = merged_production.get("marketplaces")
    if not isinstance(marketplaces, list) or not marketplaces:
        marketplaces = deepcopy(PRODUCTION_MARKETPLACES)
    normalized = []
    allowed_ids = {item["id"] for item in PRODUCTION_MARKETPLACES}
    defaults_by_id = {item["id"]: item for item in PRODUCTION_MARKETPLACES}
    seen = set()
    for item in marketplaces:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("id") or "").strip()
        if source_id not in allowed_ids or source_id in seen:
            continue
        merged = dict(defaults_by_id[source_id])
        merged.update(item)
        merged["id"] = source_id
        normalized.append(merged)
        seen.add(source_id)
    for source in PRODUCTION_MARKETPLACES:
        if source["id"] not in seen:
            normalized.append(dict(source))

    merged_production["marketplaces"] = normalized
    data["production"] = merged_production
    return data


def ui_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg = load_config(path)
    return {
        "app_name": cfg.get("app_name", "PUMA Platform"),
        "app_version": cfg.get("app_version", "v1.3"),
        "brand_line": cfg.get("brand_line", "Made by Пума (Чернявський А.)"),
        "analysis_module_name": cfg.get("analysis_module_name", "доПУМАгатель"),
        "content_module_name": cfg.get("content_module_name", "ПереводоПУМОгатель"),
        "marketplaces": deepcopy(cfg["production"]["marketplaces"]),
    }


def production_marketplace_ids(path: str | Path | None = None) -> tuple[str, ...]:
    return tuple(item["id"] for item in load_config(path)["production"]["marketplaces"])
