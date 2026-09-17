from puma_scouts.models import IdentityConfidence, Marketplace, Offer, ProductMission, Verdict
from puma_scouts.validator import validate_offer
from puma_scouts.variant_engine import named_generations


def _offer(mission, title, *, marketplace=Marketplace.EPICENTR, price=500, attrs=None):
    return Offer(
        article=mission.article,
        marketplace=marketplace,
        title=title,
        price=price,
        currency="UAH",
        availability="InStock",
        url="https://example.com/product",
        attributes=attrs or {},
    )


def test_tool_descriptor_before_expected_brand_is_not_foreign_brand():
    mission = ProductMission(
        article="36-031",
        source_data={
            "name": "Молоток Polax слесарный c ручкой из дерева 1000 г DIN 1041 (36-031)",
            "brand": "Polax",
        },
    )
    checked = validate_offer(
        mission,
        _offer(
            mission,
            "Молоток Polax слесарный c ручкой из дерева 1000 г DIN 1041 (36-031)",
            attrs={"brand": "Polax"},
        ),
    )

    assert checked.verdict == Verdict.PASS, checked
    assert checked.identity_confidence == IdentityConfidence.CONFIRMED, checked
    assert not any("foreign leading brand" in x for x in checked.conflicts), checked


def test_separated_neighbor_model_family_must_conflict_sgr70_vs_sgn125():
    mission = ProductMission(
        article="SGR-70",
        source_data={
            "name": "Генератор дизельный Soygen SGR-70 50 кВт 70 кВА 380 В",
            "brand": "Soygen",
        },
    )
    checked = validate_offer(
        mission,
        _offer(
            mission,
            "Генератор дизельный Soygen SGN 125 100 кВт 3 фазный промышленный",
            attrs={"brand": "Soygen"},
            price=677879,
        ),
    )

    assert checked.verdict != Verdict.PASS, checked
    assert any("model family mismatch" in x or "product family mismatch" in x for x in checked.conflicts), checked


def test_mixed_alphanumeric_model_token_is_not_parsed_as_generation_number():
    text = "Портативная батарея XON PowerBoost 25000 mAh 500A peak 1000A Черный (TC1N 5887)"
    generations = named_generations(text)

    assert "черный" not in generations, generations
    assert generations == {}, generations


def test_xon_ukrainian_candidate_with_same_physical_identity_passes():
    mission = ProductMission(
        article="05060948065887",
        source_data={
            "name": "Портативная батарея с функцией автозапуска XON PowerBoost 25000 mAh 500A peak 1000A Черный (TC1N 5887)",
            "brand": "XON",
        },
    )
    checked = validate_offer(
        mission,
        _offer(
            mission,
            "Портативна батарея з функцією автозапуску XON PowerBoost 25000 mAh 500A peak 1000A Чорний (TC1N 5887)",
            marketplace=Marketplace.PROM,
            price=2377,
            attrs={"brand": "XON"},
        ),
    )

    assert checked.verdict == Verdict.PASS, checked
    assert checked.identity_confidence in {IdentityConfidence.CONFIRMED, IdentityConfidence.PROBABLE}, checked
