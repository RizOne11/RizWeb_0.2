import pytest

from puma_scouts.models import IdentityConfidence, Marketplace, Offer, ProductMission, Verdict
from puma_scouts.validator import validate_offer
from puma_scouts.category_profiles import classify_category


def _offer(mission, title, *, marketplace=Marketplace.PROM, brand=""):
    return Offer(
        article=mission.article,
        marketplace=marketplace,
        title=title,
        price=1000,
        currency="UAH",
        availability="InStock",
        url="https://example.com/product",
        attributes={"brand": brand} if brand else {},
    )


def test_classifier_detects_computer_variant_profile():
    mission = ProductMission(
        article="15067f64-2a1a-457b-9920-d5d4c2e3de7e",
        source_data={
            "name": "Ноутбук Refurb Lenovo ThinkPad L490 FHD i5-8265U/16/1TBSSD Class A-",
            "brand": "Lenovo",
        },
    )
    assert classify_category(mission) == "computer_variant"


def test_classifier_detects_consumable_multipack_profile():
    mission = ProductMission(
        article="X-Treme28",
        source_data={
            "name": "Баллон газовый универсальный X-Treme 227 г 28 шт (X-Treme28)",
            "brand": "X-Treme",
        },
    )
    assert classify_category(mission) == "consumable_multipack"


def test_classifier_detects_cable_length_profile():
    mission = ProductMission(
        article="A147-10m",
        source_data={
            "name": "Оптоволоконный кабель Digital HDMI-HDMI 2.1 8K 60Hz Jasoz A147 10 м Черный (A147-10m)",
            "brand": "Jasoz",
        },
    )
    assert classify_category(mission) == "cable_length_variant"


@pytest.mark.parametrize(
    "candidate",
    [
        "Зарядное устройство для ноутбука Lenovo ThinkPad L490 45 W",
        "Клавиатура для ноутбука Lenovo ThinkPad L490 (01YN362)",
        "Аккумулятор для Lenovo ThinkPad L490",
    ],
)
def test_l490_rejects_laptop_accessories(candidate):
    mission = ProductMission(
        article="15067f64-2a1a-457b-9920-d5d4c2e3de7e",
        source_data={
            "name": "Ноутбук Refurb Lenovo ThinkPad L490 FHD i5-8265U/16/1TBSSD Class A-",
            "brand": "Lenovo",
        },
    )
    checked = validate_offer(mission, _offer(mission, candidate, brand="Lenovo"))
    assert checked.verdict != Verdict.PASS, checked
    assert any("accessory" in reason or "component" in reason for reason in checked.conflicts), checked


@pytest.mark.parametrize(
    "candidate,needle",
    [
        ("Ноутбук Lenovo ThinkPad L490 FHD i5-8265U/16/256SSD Class A-", "storage"),
        ("Ноутбук Lenovo ThinkPad L490 FHD i5-8365U/16/1TBSSD Class A-", "cpu"),
    ],
)
def test_l490_rejects_explicit_configuration_conflicts(candidate, needle):
    mission = ProductMission(
        article="15067f64-2a1a-457b-9920-d5d4c2e3de7e",
        source_data={
            "name": "Ноутбук Refurb Lenovo ThinkPad L490 FHD i5-8265U/16/1TBSSD Class A-",
            "brand": "Lenovo",
        },
    )
    checked = validate_offer(mission, _offer(mission, candidate, brand="Lenovo"))
    assert checked.verdict != Verdict.PASS, checked
    assert any(needle in reason.casefold() for reason in checked.conflicts), checked


def test_l490_missing_storage_is_probable_not_confirmed():
    mission = ProductMission(
        article="15067f64-2a1a-457b-9920-d5d4c2e3de7e",
        source_data={
            "name": "Ноутбук Refurb Lenovo ThinkPad L490 FHD i5-8265U/16/1TBSSD Class A-",
            "brand": "Lenovo",
        },
    )
    checked = validate_offer(
        mission,
        _offer(mission, "Ноутбук Lenovo ThinkPad L490 FHD i5-8265U 16GB Class A-", brand="Lenovo"),
    )
    assert checked.verdict == Verdict.PASS, checked
    assert checked.identity_confidence == IdentityConfidence.PROBABLE, checked


def test_exact_l490_configuration_stays_confirmed():
    mission = ProductMission(
        article="15067f64-2a1a-457b-9920-d5d4c2e3de7e",
        source_data={
            "name": "Ноутбук Refurb Lenovo ThinkPad L490 FHD i5-8265U/16/1TBSSD Class A-",
            "brand": "Lenovo",
        },
    )
    checked = validate_offer(
        mission,
        _offer(mission, "Ноутбук Lenovo ThinkPad L490 FHD i5-8265U/16/1TBSSD Class A-", brand="Lenovo"),
    )
    assert checked.verdict == Verdict.PASS, checked
    assert checked.identity_confidence == IdentityConfidence.CONFIRMED, checked


@pytest.mark.parametrize(
    "candidate",
    [
        "Баллон газовый универсальный X-Treme 227 г",
        "Баллон газовый универсальный X-Treme 227 г 1 шт",
        "Баллон газовый универсальный X-Treme 227 г 24 шт",
    ],
)
def test_x_treme_28_does_not_confirm_wrong_or_unknown_pack(candidate):
    mission = ProductMission(
        article="X-Treme28",
        source_data={
            "name": "Баллон газовый универсальный X-Treme 227 г 28 шт (X-Treme28)",
            "brand": "X-Treme",
        },
    )
    checked = validate_offer(mission, _offer(mission, candidate, brand="X-Treme"))
    if "24 шт" in candidate or "1 шт" in candidate:
        assert checked.verdict != Verdict.PASS, checked
    else:
        assert checked.verdict == Verdict.PASS, checked
        assert checked.identity_confidence == IdentityConfidence.PROBABLE, checked


def test_x_treme_28_exact_pack_stays_confirmed():
    mission = ProductMission(
        article="X-Treme28",
        source_data={
            "name": "Баллон газовый универсальный X-Treme 227 г 28 шт (X-Treme28)",
            "brand": "X-Treme",
        },
    )
    checked = validate_offer(
        mission,
        _offer(mission, "Баллон газовый универсальный X-Treme 227 г 28 шт", brand="X-Treme"),
    )
    assert checked.verdict == Verdict.PASS, checked
    assert checked.identity_confidence == IdentityConfidence.CONFIRMED, checked


@pytest.mark.parametrize(
    "candidate",
    [
        "Оптоволоконний кабель HDMI 2.1 8K 60Hz 15м Jasoz A147 (A147-15m)",
        "Оптоволоконный кабель Digital HDMI-HDMI 2.1 8K 60Hz Jasoz A147 30 м (A147-30m)",
    ],
)
def test_a147_10m_rejects_sibling_lengths(candidate):
    mission = ProductMission(
        article="A147-10m",
        source_data={
            "name": "Оптоволоконный кабель Digital HDMI-HDMI 2.1 8K 60Hz Jasoz A147 10 м Черный (A147-10m)",
            "brand": "Jasoz",
        },
    )
    checked = validate_offer(mission, _offer(mission, candidate, brand="Jasoz"))
    assert checked.verdict != Verdict.PASS, checked
    assert any("length" in reason.casefold() for reason in checked.conflicts), checked


def test_a147_10m_exact_length_stays_confirmed():
    mission = ProductMission(
        article="A147-10m",
        source_data={
            "name": "Оптоволоконный кабель Digital HDMI-HDMI 2.1 8K 60Hz Jasoz A147 10 м Черный (A147-10m)",
            "brand": "Jasoz",
        },
    )
    checked = validate_offer(
        mission,
        _offer(mission, "Оптоволоконний кабель HDMI 2.1 8K 60Hz 10м Jasoz A147 (A147-10m)", brand="Jasoz"),
    )
    assert checked.verdict == Verdict.PASS, checked
    assert checked.identity_confidence == IdentityConfidence.CONFIRMED, checked



def test_classifier_detects_energy_power_profile():
    mission = ProductMission(
        article="M1202",
        source_data={
            "name": "Инвертор Must PV1800 PV18-2012 ECO 2 кВт 12В MPPT 80А с чистой синусоидой Белый (M1202)",
            "brand": "Must",
        },
    )
    assert classify_category(mission) == "energy_power"


@pytest.mark.parametrize(
    "candidate,needle",
    [
        ("Инвертор Must Solar PV1800 VPK 3000 W 24В+ в сборе", "power"),
        ("Система автономная с инвертором Must PV1800 PV18-2012 ECO 2000 Вт 12V и аккумулятором 12,8V 100A", "bundle"),
        ("MUST PV18-2012 PRO", "edition"),
    ],
)
def test_must_inverter_rejects_wrong_energy_variant(candidate, needle):
    mission = ProductMission(
        article="M1202",
        source_data={
            "name": "Инвертор Must PV1800 PV18-2012 ECO 2 кВт 12В MPPT 80А с чистой синусоидой Белый (M1202)",
            "brand": "Must",
        },
    )
    checked = validate_offer(mission, _offer(mission, candidate, brand="Must"))
    assert checked.verdict != Verdict.PASS, checked
    assert any(needle in reason.casefold() for reason in checked.conflicts), checked


def test_must_inverter_exact_variant_stays_confirmed():
    mission = ProductMission(
        article="M1202",
        source_data={
            "name": "Инвертор Must PV1800 PV18-2012 ECO 2 кВт 12В MPPT 80А с чистой синусоидой Белый (M1202)",
            "brand": "Must",
        },
    )
    checked = validate_offer(
        mission,
        _offer(mission, "Инвертор Must PV1800 PV18-2012 ECO 2 кВт 12В MPPT 80А", brand="Must"),
    )
    assert checked.verdict == Verdict.PASS, checked
    assert checked.identity_confidence == IdentityConfidence.CONFIRMED, checked


def test_classifier_detects_wearable_model_profile():
    mission = ProductMission(
        article="KMR00010B",
        source_data={"name": "Смарт-часы Kospet MAGIC R10 Black (KMR00010B)", "brand": "Kospet"},
    )
    assert classify_category(mission) == "wearable_model_variant"


def test_kospet_magic_r10_rejects_p10():
    mission = ProductMission(
        article="KMR00010B",
        source_data={"name": "Смарт-часы Kospet MAGIC R10 Black (KMR00010B)", "brand": "Kospet"},
    )
    checked = validate_offer(
        mission,
        _offer(mission, "Часы KOSPET MAGIC P10 Smartwatch", brand="Kospet"),
    )
    assert checked.verdict != Verdict.PASS, checked
    assert any("wearable model" in reason.casefold() for reason in checked.conflicts), checked


@pytest.mark.parametrize(
    "candidate",
    [
        "Смарт-годинник тактичний Kospet Tank T4 Black (KTT0004B)",
        "Смарт-годинник Kospet Tank T4 Special Edition Black Gold (KTT0004MG)",
    ],
)
def test_kospet_t4_special_edition_rejects_neighbor_sku(candidate):
    mission = ProductMission(
        article="KTT0004SEB",
        source_data={
            "name": "Смарт-часы тактические Kospet Tank T4 Special Edition Black (KTT0004SEB)",
            "brand": "Kospet",
        },
    )
    checked = validate_offer(mission, _offer(mission, candidate, brand="Kospet"))
    assert checked.verdict != Verdict.PASS, checked
    assert any("wearable sku" in reason.casefold() or "edition" in reason.casefold() for reason in checked.conflicts), checked


def test_kospet_t4_special_edition_exact_stays_confirmed():
    mission = ProductMission(
        article="KTT0004SEB",
        source_data={
            "name": "Смарт-часы тактические Kospet Tank T4 Special Edition Black (KTT0004SEB)",
            "brand": "Kospet",
        },
    )
    checked = validate_offer(
        mission,
        _offer(
            mission,
            "Смарт-годинник тактичний Kospet Tank T4 Special Edition Black (KTT0004SEB)",
            brand="Kospet",
        ),
    )
    assert checked.verdict == Verdict.PASS, checked
    assert checked.identity_confidence == IdentityConfidence.CONFIRMED, checked



def test_classifier_detects_apparel_size_profile_from_mixed18_swimwear():
    mission = ProductMission(
        article="162SW21СBLS",
        source_data={
            "name": "Купальник закрытый с чашками Perfect Female beach comfort S Черный (162SW/21С/BL)",
            "brand": "Perfect Female",
        },
    )
    assert classify_category(mission) == "apparel_size_variant"


@pytest.mark.parametrize(
    "source_name,candidate",
    [
        (
            "Купальник закрытый с чашками Perfect Female beach comfort S Черный",
            "Купальник закрытый с чашками Perfect Female beach comfort M Черный",
        ),
        (
            "Пижама Perfect Female Молочный M (186Pj-35)",
            "Пижама Perfect Female Молочный XL (186Pj-35)",
        ),
        (
            "Комплект белья Perfect Female Красный XS/85АA (173LS-27HE-r)",
            "Комплект белья Perfect Female Красный S/85B (173LS-27HE-r)",
        ),
        (
            "Бутсы футбольные OWAXX 180916 43 Красный",
            "Бутсы футбольные OWAXX 180916 42 Красный",
        ),
    ],
)
def test_apparel_profile_rejects_neighbor_size_variants(source_name, candidate):
    mission = ProductMission(
        article="ROW-APPAREL",
        source_data={"name": source_name, "brand": source_name.split()[1]},
    )
    checked = validate_offer(mission, _offer(mission, candidate, brand=mission.source_data["brand"]))

    assert checked.verdict != Verdict.PASS, checked
    assert any("apparel size mismatch" in reason.casefold() for reason in checked.conflicts), checked


@pytest.mark.parametrize(
    "source_name,candidate",
    [
        (
            "Купальник закрытый с чашками Perfect Female beach comfort S Черный",
            "Купальник Perfect Female beach comfort S Черный",
        ),
        (
            "Пижама Perfect Female Молочный M (186Pj-35)",
            "Пижама Perfect Female Молочный M (186Pj-35)",
        ),
        (
            "Комплект белья Perfect Female Красный XS/85АA (173LS-27HE-r)",
            "Комплект белья Perfect Female Красный XS/85AA (173LS-27HE-r)",
        ),
        (
            "Бутсы футбольные OWAXX 180916 43 Красный",
            "Бутсы футбольные OWAXX 180916 43 Красный",
        ),
    ],
)
def test_apparel_profile_preserves_same_size_variants(source_name, candidate):
    brand = "Perfect Female" if "Perfect Female" in source_name else "OWAXX"
    mission = ProductMission(
        article="ROW-APPAREL",
        source_data={"name": source_name, "brand": brand},
    )
    checked = validate_offer(mission, _offer(mission, candidate, brand=brand))

    assert not any("apparel size mismatch" in reason.casefold() for reason in checked.conflicts), checked


def test_apparel_profile_missing_size_downgrades_confirmation_not_rejects():
    mission = ProductMission(
        article="ROW-APPAREL",
        source_data={
            "name": "Куртка Intruder Easy softshell XL Хаки",
            "brand": "Intruder",
            "model": "Easy",
        },
    )
    checked = validate_offer(
        mission,
        _offer(mission, "Куртка Intruder Easy softshell Хаки", brand="Intruder"),
    )

    assert checked.verdict == Verdict.PASS, checked
    assert checked.identity_confidence == IdentityConfidence.PROBABLE, checked
    assert any("apparel size" in evidence.casefold() for evidence in checked.positive_evidence), checked
