from priceintel.runner import _search_matrix_queries, _run_search_matrix
from priceintel.matcher import classify_match

ROW = {
    "Название": 'Монитор Xiaomi Redmi A27Q 2025 P27QCB-RA 2560x1440 2K IPS 100 Гц 27" Черный (2288)',
    "Производитель": "Xiaomi",
    "Артикул": "002288",
    "Параметры": [],
}

MARKETS = [
    {"name": "Rozetka", "domain": "rozetka.com.ua"},
    {"name": "Prom", "domain": "prom.ua"},
    {"name": "Epicentr", "domain": "epicentrk.ua"},
    {"name": "Allo", "domain": "allo.ua"},
    {"name": "Foxtrot", "domain": "foxtrot.com.ua"},
    {"name": "Comfy", "domain": "comfy.ua"},
    {"name": "Kasta", "domain": "kasta.ua"},
    {"name": "Hotline", "domain": "hotline.ua"},
]


def test_xiaomi_query_matrix_contains_public_model_and_supplier_sku_variants():
    q = _search_matrix_queries(ROW, 12)
    joined = " | ".join(q)
    assert 'P27QCB-RA' in joined
    assert '002288' in joined
    assert '2288' in joined
    assert 'A27Q' in joined


def test_exact_monitor_without_supplier_sku_is_accepted():
    title = 'Монітор 27" 2K Xiaomi Redmi A27Q 2025 P27QCB-RA 2560x1440 IPS 100 Гц чорний'
    m = classify_match(ROW, title)
    assert m["status"] == "EXACT"


def test_wrong_monitor_variant_is_conflict_even_with_same_model_family():
    title = 'Монітор Xiaomi Redmi A27Q 2025 P27QCB-RA 1920x1080 IPS 120 Hz 27" чорний'
    m = classify_match(ROW, title)
    assert m["status"] == "CONFLICT"
    assert "120hz" in m["reason"] or "resolution" in m["reason"]


class FakeSearcher:
    def __init__(self):
        self.calls = []

    def search_all(self, query, domains, limit_per_domain=20, exact_query=True):
        self.calls.append((query, tuple(domains)))
        result = {d: [] for d in domains}
        result["__other__"] = []
        # Return one synthetic candidate for site-targeted queries to prove merge works.
        if query.startswith('"P27QCB-RA"') and 'site:' in query:
            d = domains[0]
            result[d] = [{
                "title": "Xiaomi Redmi A27Q 2025 P27QCB-RA",
                "url": f"https://{d}/product/p27qcb-ra",
                "canonical_url": f"https://{d}/product/p27qcb-ra",
                "search_query": query,
            }]
        return result


def test_search_matrix_targets_every_marketplace_with_site_queries():
    f = FakeSearcher()
    cfg = {
        "search_matrix_max_queries": 4,
        "broad_search_matrix_max_queries": 2,
        "marketplace_search_matrix_max_queries": 4,
        "marketplace_search_matrix_run_all": True,
        "marketplace_candidate_pool_target": 5,
        "marketplace_min_queries_before_stop": 2,
        "max_results_per_marketplace": 20,
        "other_ua_shops_max_hits": 80,
    }
    grouped, matrix, errors = _run_search_matrix(ROW, MARKETS, f, cfg, lambda *_: None)
    assert not errors
    for mp in MARKETS:
        domain = mp["domain"]
        assert any((f"site:{domain}" in q and domains == (domain,)) for q, domains in f.calls)
        assert grouped[domain], f"expected a synthetic candidate for {domain}"
