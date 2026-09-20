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


def test_outgoing_query_canonicalizes_mixed_model_without_touching_normal_prose():
    mission = ProductMission(
        article="ROW-LEB",
        source_data={
            "name": "Змішувач Example LEB1-А123MG",
            "brand": "Example",
            "model": "LEB1-А123MG",
        },
    )
    queries = generate_queries(mission)
    assert any("Змішувач" in query and "LEB1-A123MG" in query for query in queries), queries
    assert all("А123MG" not in query for query in queries), queries


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
