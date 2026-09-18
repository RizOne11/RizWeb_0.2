from puma_scouts.lingua import query_language_variants
from puma_scouts.models import ProductMission
from puma_scouts.query import generate_queries
from puma_scouts.validator_base import _brand_match, _norm


def test_russian_discovery_name_gets_ukrainian_query_variant_without_article():
    mission = ProductMission(
        article="2104618962",
        source_data={
            "name": "Обогреватель керамический Emby CHT-500 Черный (2104618962)",
            "brand": "Emby",
            "model": "CHT-500",
        },
    )
    queries = generate_queries(mission)
    folded = [q.casefold() for q in queries]
    assert any("обігрівач" in q and "керамічний" in q and "чорний" in q for q in folded)
    assert all("2104618962" not in q for q in folded)


def test_ukrainian_discovery_name_gets_russian_query_variant():
    variants = [q.casefold() for q in query_language_variants("Навушники бездротові чорний")]
    assert "наушники беспроводные черный" in variants


def test_ru_ua_match_normalization_uses_same_legacy_token_form():
    assert _norm("Монітор ігровий чорний") == _norm("Монитор игровой черный")


def test_brand_aliases_from_priceintel_are_confirmed():
    assert _brand_match("Xiaomi", "Монітор Redmi A27Q 2025")
    assert _brand_match("Xiaomi", "Смартфон POCO X6 Pro")
    assert _brand_match("Samsung", "Galaxy A55 5G")
    assert _brand_match("Huawei", "Honor 20")


def test_short_mi_alias_is_boundary_aware():
    assert _brand_match("Xiaomi", "Mi Band 9")
    assert not _brand_match("Xiaomi", "Premium monitor A27Q")
