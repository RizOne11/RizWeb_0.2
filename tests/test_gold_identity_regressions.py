import asyncio

from puma_scouts.models import IdentityConfidence, Marketplace, Offer, ProductMission, Verdict
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


def test_public_short_article_inside_title_must_not_zero_out_queries():
    mission = ProductMission(
        article="35-005",
        source_data={
            "name": "Бокорезы Polax 180 мм (35-005)",
            "brand": "Polax",
        },
    )
    queries = asyncio.run(PromScout(timeout=1).generate_queries(mission))

    assert queries, "A public short article embedded in the human product title must not produce zero discovery queries"
    assert any("35-005" in q or "Бокорезы Polax" in q for q in queries)


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
        "An exact public article/SKU copied in the source product name and candidate SKU must be strong identity evidence"
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
