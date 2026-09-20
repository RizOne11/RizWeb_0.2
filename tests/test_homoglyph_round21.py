from puma_scouts.category_profiles import _norm as category_norm
from puma_scouts.identity_map import mission_identity_key, mission_identity_version
from puma_scouts.lingua import fold_homoglyphs, identity_pattern
from puma_scouts.models import Marketplace, Offer, ProductMission, Verdict
from puma_scouts.query import generate_queries, identifier_in_text
from puma_scouts.validator import validate_offer
from puma_scouts.validator_base import _brand_match
from puma_scouts.variant_engine import explicit_model_agreement


def _offer(mission: ProductMission, title: str) -> Offer:
    return Offer(
        article=mission.article,
        marketplace=Marketplace.EPICENTR,
        title=title,
        price=1000,
        currency="UAH",
        availability="InStock",
        url="https://example.com/product",
        attributes={"brand": "Example"},
    )


def test_real_mixed_catalog_tokens_fold_to_clean_latin_identity():
    assert fold_homoglyphs("1060-ТE-Р038BL") == "1060-te-p038bl"
    assert fold_homoglyphs("EPСС2614") == "epcc2614"
    assert fold_homoglyphs("LEB1-А123MG") == "leb1-a123mg"
    assert fold_homoglyphs("MВS-4708") == "mbs-4708"


def test_uppercase_ukrainian_i_inside_latin_brand_folds_to_i():
    assert fold_homoglyphs("NІKE") == "nike"
    assert _brand_match("NIKE", "Кросівки NІKE Air Max")


def test_spaced_dimension_cyrillic_x_and_multiplication_sign_are_canonical():
    assert fold_homoglyphs("129 х 90") == "129x90"
    assert fold_homoglyphs("129 × 90") == "129x90"
    assert fold_homoglyphs("129x90") == "129x90"


def test_identifier_pattern_matches_clean_and_mixed_script_both_directions():
    assert identity_pattern("EPCC2614").search("Ортез EPСС2614")
    assert identity_pattern("EPСС2614").search("Ортез EPCC2614")
    assert identifier_in_text("MBS-4708", "Товар MВS-4708")
    assert identifier_in_text("MВS-4708", "Товар MBS-4708")


def test_variant_engine_model_agreement_is_symmetric_for_homoglyphs():
    assert explicit_model_agreement("Example EPСС2614", "Example EPCC2614") == {"epcc2614"}
    assert explicit_model_agreement("Example EPCC2614", "Example EPСС2614") == {"epcc2614"}


def test_validator_accepts_mixed_source_and_clean_candidate():
    mission = ProductMission(
        article="ROW-EPCC",
        source_data={"name": "Ортез Example EPСС2614", "brand": "Example", "model": "EPСС2614"},
    )
    checked = validate_offer(mission, _offer(mission, "Ортез Example EPCC2614"))
    assert checked.verdict == Verdict.PASS, checked


def test_validator_accepts_clean_source_and_mixed_candidate():
    mission = ProductMission(
        article="ROW-EPCC",
        source_data={"name": "Ортез Example EPCC2614", "brand": "Example", "model": "EPCC2614"},
    )
    checked = validate_offer(mission, _offer(mission, "Ортез Example EPСС2614"))
    assert checked.verdict == Verdict.PASS, checked


def test_wrong_neighbor_model_remains_conflict_after_homoglyph_folding():
    mission = ProductMission(
        article="ROW-EPCC",
        source_data={"name": "Ортез Example EPCC2614", "brand": "Example", "model": "EPCC2614"},
    )
    checked = validate_offer(mission, _offer(mission, "Ортез Example EPСС2615"))
    assert checked.verdict != Verdict.PASS, checked
    assert checked.conflicts, checked


def test_query_removes_supplier_article_even_when_scripts_are_mixed():
    mission = ProductMission(
        article="EPСС2614",
        source_data={"name": "Ортез Example EPCC2614 129 х 90", "brand": "Example"},
    )
    queries = generate_queries(mission)
    assert queries
    assert all(not identifier_in_text("EPCC2614", query) for query in queries), queries
    assert all(not identifier_in_text("EPСС2614", query) for query in queries), queries
    assert any("129x90" in query for query in queries), queries


def test_outgoing_query_keeps_literal_and_canonical_mixed_model_variants():
    mission = ProductMission(
        article="ROW-LEB",
        source_data={
            "name": "Змішувач Example LEB1-А123MG",
            "brand": "Example",
            "model": "LEB1-А123MG",
        },
    )
    queries = generate_queries(mission)
    assert any("Змішувач" in query and "LEB1-А123MG" in query for query in queries), queries
    assert any("Змішувач" in query and "LEB1-A123MG" in query for query in queries), queries


def test_identity_key_and_version_are_stable_across_homoglyph_variants():
    mixed = ProductMission(
        article="EPСС2614",
        source_data={
            "supplier": "Hubber",
            "name": "Ортез Example EPСС2614",
            "brand": "Example",
            "model": "EPСС2614",
        },
    )
    clean = ProductMission(
        article="EPCC2614",
        source_data={
            "supplier": "Hubber",
            "name": "Ортез Example EPCC2614",
            "brand": "Example",
            "model": "EPCC2614",
        },
    )
    assert mission_identity_key(mixed) == mission_identity_key(clean)
    assert mission_identity_version(mixed) == mission_identity_version(clean)


def test_category_profiles_use_the_same_canonical_identity_text():
    assert category_norm("NІKE 129 х 90 EPСС2614") == "nike 129x90 epcc2614"
    assert category_norm("NIKE 129 × 90 EPCC2614") == "nike 129x90 epcc2614"


def test_pure_cyrillic_alphanumeric_units_and_bundle_notation_are_not_overfolded():
    assert fold_homoglyphs("500Вт") == "500вт"
    assert fold_homoglyphs("3в1") == "3в1"
    assert fold_homoglyphs("ВТ6778") == "вт6778"


def test_mixed_script_normal_words_are_not_overtransliterated():
    assert fold_homoglyphs("Cеро-розовый") == "cеро-розовый"
    assert fold_homoglyphs("186Pj35Кофта") == "186pj35кофта"


def test_punctuation_separated_homoglyph_code_segments_are_folded():
    assert fold_homoglyphs("BZ-425.М") == "bz-425.m"
    assert fold_homoglyphs("OLS-PL-30.К") == "ols-pl-30.k"
    assert identity_pattern("BZ-425.М").search("Дорожка Abarqs BZ-425M Black")


def test_size_abbreviation_without_digits_is_not_treated_as_identifier_code():
    assert fold_homoglyphs("р.S") == "р.s"


def test_perfect_female_mixed_size_query_keeps_literal_and_canonical_forms():
    mission = ProductMission(
        article="173LS27HErXS85АA",
        source_data={
            "name": "Комплект белья с высокой посадкой Perfect Female Красный XS/85АA (173LS-27HE-r)",
            "brand": "Perfect Female",
        },
    )
    queries = generate_queries(mission)
    assert any("85АA" in query for query in queries), queries
    assert any("85AA" in query for query in queries), queries
    assert all(not identifier_in_text(mission.article, query) for query in queries), queries


def test_commercial_old_price_cannot_become_model_identity():
    mission = ProductMission(
        article="2069180735",
        source_data={
            "name": "Металлический стеллаж Emby Light Series 2100х900x600 мм 5 полок ДСП до 100 кг Белый",
            "brand": "Emby",
            "old_price": "4799.0",
        },
    )
    checked = validate_offer(
        mission,
        _offer(
            mission,
            "Металевий стелаж Emby Light Series 2100х900x600 мм 5 полиць ДСП до 100 кг Білий",
        ),
    )
    assert checked.verdict == Verdict.PASS, checked
    assert not any("emby4799" in reason for reason in checked.conflicts), checked


def test_multidimensional_size_formatting_matches_but_real_dimension_change_conflicts():
    mission = ProductMission(
        article="2069180735",
        source_data={
            "name": "Стеллаж Emby Light Series 2100 х 900 × 600 мм Белый",
            "brand": "Emby",
        },
    )
    same = validate_offer(
        mission,
        _offer(mission, "Стелаж Emby Light Series 2100x900x600мм Білий"),
    )
    wrong = validate_offer(
        mission,
        _offer(mission, "Стелаж Emby Light Series 2100x900x500 мм Білий"),
    )
    assert same.verdict == Verdict.PASS, same
    assert wrong.verdict != Verdict.PASS, wrong
    assert any("size/volume mismatch" in reason for reason in wrong.conflicts), wrong


def test_perfect_female_real_mixed_script_offer_still_passes():
    mission = ProductMission(
        article="173LS27HErXS85АA",
        source_data={
            "name": "Комплект белья с высокой посадкой Perfect Female Красный XS/85АA (173LS-27HE-r)",
            "brand": "Perfect Female",
        },
    )
    checked = validate_offer(
        mission,
        _offer(
            mission,
            "Комплект білизни з високою посадкою Perfect Female Червоний XS/85АA (173LS-27HE-r) D12-2026",
        ),
    )
    assert checked.verdict == Verdict.PASS, checked


def test_degrenne_dimension_only_false_positive_stays_rejected():
    mission = ProductMission(
        article="229260",
        source_data={
            "name": "Набор салфеток 2 шт Degrenne Paris Linge de Table 35x50см Коралловый 229260",
            "brand": "Degrenne Paris",
        },
    )
    checked = validate_offer(
        mission,
        _offer(mission, "Lefard Серветка Home Textile Peeps 35x50см (732-287)"),
    )
    assert checked.verdict != Verdict.PASS, checked
    assert any("brand not confirmed" in reason for reason in checked.conflicts), checked
