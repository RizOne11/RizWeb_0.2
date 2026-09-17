from decimal import Decimal

from puma_scouts.models import Marketplace, Offer, ProductMission, Verdict
from puma_scouts.validator import validate_offer


def _validate(mission: ProductMission, title: str, marketplace: Marketplace = Marketplace.PROM):
    offer = Offer(
        article=mission.article,
        marketplace=marketplace,
        title=title,
        price=Decimal("999.00"),
        url="https://example.com/product",
    )
    return validate_offer(mission, offer)


def _marshall() -> ProductMission:
    return ProductMission(
        article="11676",
        source_data={
            "name": "Комплект наушники с кейсом Marshall Major IV Bluetooth Black (1005773)",
            "brand": "Marshall",
            "model": "Major IV",
        },
    )


def _emby() -> ProductMission:
    return ProductMission(
        article="1724889898",
        source_data={
            "name": "Обогреватель керамический Emby CHT-500 на 10 кв.м Белый",
            "brand": "Emby",
            "model": "CHT-500",
        },
    )


def test_marshall_real_headphones_still_pass():
    result = _validate(_marshall(), "Навушники Marshall Major IV Bluetooth Black 1005773")
    assert result.verdict == Verdict.PASS, result


def test_marshall_earpads_do_not_enter_market_basket():
    bad_titles = [
        "Амбушури для навушників Marshall Major IV/4 чорні",
        "Тканинні амбушури Marshall Major III IV V",
        "Накладка на оголовье для наушников Marshall Major 3 4 5 III IV V",
    ]
    for title in bad_titles:
        result = _validate(_marshall(), title)
        assert result.verdict != Verdict.PASS, (title, result)


def test_emby_real_heater_still_pass():
    result = _validate(_emby(), "Керамический обогреватель Emby CHT-500 белый")
    assert result.verdict == Verdict.PASS, result


def test_emby_foreign_brand_same_model_does_not_enter_market_basket():
    result = _validate(_emby(), "Керамический обогреватель SunCeramic CHT-500 500 Вт")
    assert result.verdict != Verdict.PASS, result


def test_model_separator_collision_cht500_vs_ch_t500_is_rejected():
    result = _validate(
        _emby(),
        "Електричний офтальмологічний операційний стіл Invita CH-T500",
    )
    assert result.verdict != Verdict.PASS, result
