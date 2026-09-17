import asyncio

from puma_scouts.models import IdentityConfidence, Marketplace, Offer, ProductMission, Verdict
from puma_scouts.query import generate_queries as build_queries
from puma_scouts.scouts.catalog import PromScout
from puma_scouts.validator import validate_offer
from puma_scouts.variant_engine import named_generations


def _offer(mission, title, *, sku=None, marketplace=Marketplace.PROM, price=500):
    attrs = {"brand": "Polax"}
    if sku:
        attrs["sku"] = sku
    return Offer(
        article=mission.article,
        marketplace=marketplace,
        title=title,
        price=price,
        currency="UAH",
        availability="InStock",
        url="https://example.com/product",
        attributes=attrs,
    )


def test_supplier_article_is_never_a_discovery_key_even_when_present_in_title():
    mission = ProductMission(
        article="35-005",
        source_data={
            "name": "Бокорезы Polax 180 мм (35-005)",
            "brand": "Polax",
        },
    )

    raw_queries = build_queries(mission)
    scout_queries = asyncio.run(PromScout(timeout=1).generate_queries(mission))

    assert raw_queries, "Removing the supplier article must not leave Discovery without descriptive queries"
    assert scout_queries, "Catalog Discovery must still have descriptive queries after article removal"
    assert all("35-005" not in query for query in raw_queries), raw_queries
    assert all("35-005" not in query for query in scout_queries), scout_queries
    assert any("Бокорезы" in query and "Polax" in query for query in scout_queries), scout_queries


def test_internal_supplier_article_must_not_become_discovery_query():
    mission = ProductMission(
        article="INTERNAL-12345",
        source_data={"name": "Молоток слесарный Polax 1000 г", "brand": "Polax"},
    )
    queries = build_queries(mission)
    assert all("INTERNAL-12345" not in q for q in queries), queries


def test_explicit_external_model_remains_a_valid_discovery_identifier():
    mission = ProductMission(
        article="ROW-9911",
        source_data={
            "name": "Монитор Xiaomi Redmi A27Q 2025",
            "brand": "Xiaomi",
            "mpn": "P27QCB-RA",
        },
    )
    queries = build_queries(mission)
    assert any("P27QCB-RA" in q for q in queries), queries
    assert all("ROW-9911" not in q for q in queries), queries


def test_exact_public_short_article_can_confirm_identity():
    mission = ProductMission(
        article="01-0177",
        source_data={
            "name": 'Ящик для инструмента Polax 19" (01-0177)',
            "brand": "Polax",
        },
    )
    checked = validate_offer(
        mission,
        _offer(mission, 'Ящик для инструмента Polax 19" 01-0177', sku="01-0177", price=837),
    )

    assert checked.verdict == Verdict.PASS
    assert checked.identity_confidence == IdentityConfidence.CONFIRMED, (
        "An exact article visible on both sides may be validation evidence, but it must not drive Discovery"
    )


def test_neighboring_toolbox_sku_01_015_must_not_pass_for_01_0177():
    mission = ProductMission(
        article="01-0177",
        source_data={"name": 'Ящик для инструмента Polax 19" (01-0177)', "brand": "Polax"},
    )
    checked = validate_offer(
        mission,
        _offer(
            mission,
            "Ящик для инструментов Polax пластиковый замок 13 (01-015)",
            sku="01-015",
            marketplace=Marketplace.EPICENTR,
            price=385,
        ),
    )
    assert checked.verdict != Verdict.PASS, checked
    assert any("public article mismatch" in reason for reason in checked.conflicts), checked


def test_neighboring_toolbox_sku_01_0144_must_not_pass_for_01_0177():
    mission = ProductMission(
        article="01-0177",
        source_data={"name": 'Ящик для инструмента Polax 19" (01-0177)', "brand": "Polax"},
    )
    checked = validate_offer(
        mission,
        _offer(
            mission,
            'Ящик для інструментів Polax пластиковий з металевим замком 19" (01-0144)',
            sku="01-0144",
            price=837,
        ),
    )
    assert checked.verdict != Verdict.PASS, checked
    assert any("public article mismatch" in reason for reason in checked.conflicts), checked


def test_neighboring_cutters_sku_335_005_must_not_pass_for_35_005():
    mission = ProductMission(
        article="35-005",
        source_data={"name": "Бокорезы Polax 180 мм (35-005)", "brand": "Polax"},
    )
    checked = validate_offer(
        mission,
        _offer(
            mission,
            "Набор шарнирно-губцевый Polax пассатижи/бокорезы и отвертки (335-005)",
            sku="335-005",
            marketplace=Marketplace.EPICENTR,
            price=856,
        ),
    )
    assert checked.verdict != Verdict.PASS, checked
    assert any("public article mismatch" in reason for reason in checked.conflicts), checked


def test_toolbox_13_inch_must_not_pass_for_19_inch_even_without_sku():
    mission = ProductMission(
        article="01-0177",
        source_data={"name": 'Ящик для инструмента Polax 19" (01-0177)', "brand": "Polax"},
    )
    checked = validate_offer(
        mission,
        _offer(
            mission,
            "Пластиковий ящик для інструментів Polax з металевим замком 13 дюймів міцний органайзер для майстерні та будмайданчика",
            price=418,
        ),
    )
    assert checked.verdict != Verdict.PASS, checked
    assert any("size/volume mismatch" in reason for reason in checked.conflicts), checked


def test_dimension_phrase_is_not_invented_product_generation():
    generations = named_generations('Ящик для инструмента Polax пластиковый замок 19" (01-0177)')

    assert "замок" not in generations, 'The phrase "замок 19\"" describes a 19-inch toolbox, not generation 19'
