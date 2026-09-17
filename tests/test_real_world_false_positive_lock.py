import pytest

from puma_scouts.models import IdentityConfidence, Marketplace, Offer, ProductMission, Verdict
from puma_scouts.validator import validate_offer


def _offer(mission, title, *, brand=""):
    return Offer(
        article=mission.article,
        marketplace=Marketplace.PROM,
        title=title,
        price=1000,
        currency="UAH",
        availability="InStock",
        url="https://example.com/product",
        attributes={"brand": brand} if brand else {},
    )


@pytest.mark.parametrize(
    "article,name,brand,candidate,candidate_brand",
    [
        (
            "Buds3-black",
            "Беспроводные наушники Inspire Buds3 Black",
            "Inspire",
            "Наушники Samsung Galaxy Buds3 FE black (SM-R420NZKASEK)",
            "Samsung",
        ),
        (
            "Buds3-black",
            "Беспроводные наушники Inspire Buds3 Black",
            "Inspire",
            "Наушники OPPO Enco Buds3 ETEG1 slate black",
            "OPPO",
        ),
        (
            "2005912565",
            "Безопасный дизельный воздушный отопитель GREELITE SN99 12V 5 КВТ (2005912565)",
            "GREELITE",
            "Припій BEST Sn99.3/Bi0.7, 0,8мм, 40 г",
            "BEST",
        ),
        (
            "18606",
            "Генератор 2,5-2,8 кВт с медной обмоткой +AVR сертифицированный мотор Mast Group YH3000",
            "MAST",
            "Шеф кухонный нож 200 мм Kanetsune YH-3000 KC-922 из нержавеющей стали",
            "Kanetsune",
        ),
        (
            "18606",
            "Генератор 2,5-2,8 кВт с медной обмоткой +AVR сертифицированный мотор Mast Group YH3000",
            "MAST",
            "Навушники - Kurzweil YH 3000",
            "Kurzweil",
        ),
        (
            "1900284922",
            "Бензиновый генератор Aceceа PT-3300 3.3 кВт с медной обмоткой (1900284922)",
            "Aceceа",
            "Генератор бензиновый Edon 2,5 кВт / 220 В PT3300",
            "Edon",
        ),
        (
            "1900284922",
            "Бензиновый генератор Aceceа PT-3300 3.3 кВт с медной обмоткой (1900284922)",
            "Aceceа",
            "Генератор бензиновый OKAYAMA 2,5 кВт / 2,8 кВт 230 В PT-3300",
            "OKAYAMA",
        ),
        (
            "1724889898",
            "Обогреватель керамический Emby CHT-500 на 10 кв.м Белый",
            "Emby",
            "Електричний офтальмологічний операційний стіл Invita CH-T500",
            "Invita",
        ),
    ],
)
def test_shared_model_code_cannot_override_known_brand(
    article, name, brand, candidate, candidate_brand
):
    mission = ProductMission(article=article, source_data={"name": name, "brand": brand})
    checked = validate_offer(mission, _offer(mission, candidate, brand=candidate_brand))
    assert checked.verdict != Verdict.PASS, checked
    assert checked.identity_confidence != IdentityConfidence.CONFIRMED, checked


def test_fantech_standalone_rejects_bundle():
    mission = ProductMission(
        article="30455_2849345",
        source_data={
            "name": "Полноразмерные игровые наушники-гарнитура Fantech HQ53 Flash AUX USB 2 m Black",
            "brand": "Fantech",
        },
    )
    candidate = (
        "Комплект ігровий Fantech P51 5в1 клавіатура Shikari K515/"
        "миша Crypto VX7 / килимок Vigil MP356 / навушники Flash HQ53 з підставкою"
    )
    checked = validate_offer(mission, _offer(mission, candidate, brand="Fantech"))
    assert checked.verdict != Verdict.PASS, checked


def test_xon_exact_brand_and_model_stays_confirmed():
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
            brand="XON",
        ),
    )
    assert checked.verdict == Verdict.PASS, checked
    assert checked.identity_confidence == IdentityConfidence.CONFIRMED, checked


def test_greelite_exact_brand_and_model_stays_confirmed():
    mission = ProductMission(
        article="2005912565",
        source_data={
            "name": "Безопасный дизельный воздушный отопитель GREELITE SN99 12V 5 КВТ (2005912565)",
            "brand": "GREELITE",
        },
    )
    checked = validate_offer(
        mission,
        _offer(
            mission,
            "Автономний дизельний обігрівач GREELITE SN99 12 V 5 КВТ",
            brand="GREELITE",
        ),
    )
    assert checked.verdict == Verdict.PASS, checked
    assert checked.identity_confidence == IdentityConfidence.CONFIRMED, checked
