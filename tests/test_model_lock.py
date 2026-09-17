import pytest

from puma_scouts.models import IdentityConfidence, Marketplace, Offer, ProductMission, Verdict
from puma_scouts.validator import validate_offer


def _offer(mission, title, *, marketplace=Marketplace.PROM, price=1000):
    return Offer(
        article=mission.article,
        marketplace=marketplace,
        title=title,
        price=price,
        currency="UAH",
        availability="InStock",
        url="https://example.com/product",
        attributes={"brand": mission.source_data.get("brand", "")},
    )


@pytest.mark.parametrize("candidate", [
    "Генератор дизельний Soygen SGN-41 30 кВт 41 кВА 380 В",
    "Генератор дизельний Soygen SGN-34 24 кВт 34 кВА 380 В D11-2026",
    "Генератор дизельний Soygen SGN-55 40 кВт 55 кВА 380 В",
    "Генератор промышленный дизельный Soygen sgn-70 50 кВт/70 380 В",
])
def test_sgr70_rejects_neighbor_soygen_models(candidate):
    mission = ProductMission(
        article="SGR-70",
        source_data={
            "name": "Генератор дизельный Soygen SGR-70 50 кВт 70 кВА 380 В",
            "brand": "Soygen",
        },
    )
    checked = validate_offer(mission, _offer(mission, candidate))
    assert checked.verdict != Verdict.PASS, checked
    assert any("model" in reason or "family" in reason for reason in checked.conflicts), checked


def test_sgr70_exact_model_still_passes():
    mission = ProductMission(
        article="SGR-70",
        source_data={
            "name": "Генератор дизельный Soygen SGR-70 50 кВт 70 кВА 380 В",
            "brand": "Soygen",
        },
    )
    checked = validate_offer(
        mission,
        _offer(mission, "Генератор дизельний Soygen SGR-70 50 кВт 70 кВА 380 В"),
    )
    assert checked.verdict == Verdict.PASS, checked
    assert checked.identity_confidence == IdentityConfidence.CONFIRMED, checked


@pytest.mark.parametrize("candidate", [
    "Портативна батарея з функцією автозапуску XON PowerBoost 25000 mAh 500A peak 1000A Чорний (TC1N 2247)",
    "Портативная батарея 20000 mAh с функцией автозапуска с автоматическим воздушным насосом XON PowerBoost (TC1N 2230) Черный",
])
def test_xon_tc1n5887_rejects_neighbor_suffix(candidate):
    mission = ProductMission(
        article="05060948065887",
        source_data={
            "name": "Портативная батарея с функцией автозапуска XON PowerBoost 25000 mAh 500A peak 1000A Черный (TC1N 5887)",
            "brand": "XON",
        },
    )
    checked = validate_offer(mission, _offer(mission, candidate))
    assert checked.verdict != Verdict.PASS, checked
    assert any("model" in reason or "family" in reason for reason in checked.conflicts), checked


def test_xon_tc1n5887_ukrainian_exact_variant_passes():
    mission = ProductMission(
        article="05060948065887",
        source_data={
            "name": "Портативная батарея с функцией автозапуска XON PowerBoost 25000 mAh 500A peak 1000A Черный (TC1N 5887)",
            "brand": "XON",
        },
    )
    checked = validate_offer(
        mission,
        _offer(mission, "Портативна батарея з функцією автозапуску XON PowerBoost 25000 mAh 500A peak 1000A Чорний (TC1N 5887)"),
    )
    assert checked.verdict == Verdict.PASS, checked
