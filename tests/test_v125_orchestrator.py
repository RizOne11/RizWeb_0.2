from priceintel.runner import _search_matrix_queries
from priceintel.matcher import build_fingerprint
from priceintel.extract import availability_state
from priceintel.search import HybridSearch

ROW = {
    "Название": 'Монитор Xiaomi Redmi A27Q 2025 P27QCB-RA 2560x1440 2K IPS 100 Гц 27" Черный (2288)',
    "Производитель": "Xiaomi",
    "Артикул": "002288",
    "Параметры": [{"name": "Цвет", "value": "Черный"}, {"name": "DCI-P3", "value": "95%"}],
}


def test_dci_p3_is_not_model_identifier():
    fp = build_fingerprint(ROW)
    assert not any("DCI-P3".lower() == str(x).lower() for x in fp["models"])
    queries = " | ".join(_search_matrix_queries(ROW, 12))
    assert '"DCI-P3"' not in queries
    assert "P27QCB-RA" in queries


def test_availability_normalization():
    assert availability_state("https://schema.org/InStock") == "IN_STOCK"
    assert availability_state("Готово до відправки") == "IN_STOCK"
    assert availability_state("Є в наявності") == "IN_STOCK"
    assert availability_state("https://schema.org/OutOfStock") == "OUT_OF_STOCK"
    assert availability_state("Немає в наявності") == "OUT_OF_STOCK"
    assert availability_state("") == "UNKNOWN"


def test_hybrid_strips_site_operator_before_provider_search():
    h = HybridSearch(firecrawl_enabled=False, exa_enabled=False, serper_enabled=False)
    clean, domain = h._strip_site('"P27QCB-RA" site:prom.ua -"123"')
    assert domain == "prom.ua"
    assert "site:" not in clean
    assert "P27QCB-RA" in clean
