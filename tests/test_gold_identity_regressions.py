import asyncio

from puma_scouts.models import IdentityConfidence, Marketplace, Offer, ProductMission, Verdict
from puma_scouts.scouts.catalog import PromScout
from puma_scouts.validator import validate_offer
from puma_scouts.variant_engine import named_generations


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
    offer = Offer(
        article=mission.article,
        marketplace=Marketplace.PROM,
        title='Ящик для инструмента Polax 19" 01-0177',
        price=837,
        currency="UAH",
        availability="InStock",
        url="https://example.com/polax-01-0177",
        attributes={"sku": "01-0177", "brand": "Polax"},
    )

    checked = validate_offer(mission, offer)

    assert checked.verdict == Verdict.PASS
    assert checked.identity_confidence == IdentityConfidence.CONFIRMED, (
        "An exact public article/SKU copied in the source product name and candidate SKU must be strong identity evidence"
    )


def test_dimension_phrase_is_not_invented_product_generation():
    generations = named_generations('Ящик для инструмента Polax пластиковый замок 19" (01-0177)')

    assert "замок" not in generations, 'The phrase "замок 19\"" describes a 19-inch toolbox, not generation 19'
