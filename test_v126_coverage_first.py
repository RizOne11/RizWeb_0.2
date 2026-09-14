from priceintel.runner import _offer_identity_key, _is_direct_product_url, _prepare_candidates

ROW = {
    "Название": 'Монитор Xiaomi Redmi A27Q 2025 P27QCB-RA 2560x1440 2K IPS 100 Гц 27" Черный (2288)',
    "Производитель": "Xiaomi",
    "Артикул": "002288",
    "Параметры": [{"name": "Цвет", "value": "Черный"}],
}
MARKETS = [
    {"name": "Rozetka", "domain": "rozetka.com.ua"},
    {"name": "Prom", "domain": "prom.ua"},
    {"name": "Epicentr", "domain": "epicentrk.ua"},
    {"name": "Hotline", "domain": "hotline.ua"},
]


def hit(url, title, snippet="", position=1):
    return {"url": url, "canonical_url": url, "title": title, "snippet": snippet, "position": position}


def test_rozetka_locale_urls_dedup_to_one_offer():
    a = _offer_identity_key("rozetka.com.ua", "https://hard.rozetka.com.ua/ua/592071073/p592071073/")
    b = _offer_identity_key("rozetka.com.ua", "https://hard.rozetka.com.ua/592071073/p592071073/")
    assert a == b == "rozetka:p592071073"


def test_category_pages_are_not_direct_offers():
    assert _is_direct_product_url("rozetka.com.ua", "https://hard.rozetka.com.ua/ua/592071073/p592071073/")
    assert not _is_direct_product_url("rozetka.com.ua", "https://hard.rozetka.com.ua/monitors/c80089/producer=xiaomi/")
    assert _is_direct_product_url("prom.ua", "https://prom.ua/m5380328037794579431-monitor-redmi-a27q.html")
    assert not _is_direct_product_url("prom.ua", "https://prom.ua/ua/Monitory;283549-Redmi")
    assert _is_direct_product_url("epicentrk.ua", "https://epicentrk.ua/ua/shop/mplc-monitor-redmi-a27q-2025-p27qcb-ra.html")
    assert not _is_direct_product_url("epicentrk.ua", "https://epicentrk.ua/ua/shop/monitory/fs/chastota-obnovleniya-100/")


def test_prepare_candidates_keeps_known_exact_and_drops_noise_and_duplicates():
    exact_title = "Монітор Xiaomi Redmi A27Q 2025 P27QCB-RA 2560x1440 IPS 100 Гц 27 чорний"
    grouped = {
        "rozetka.com.ua": [
            hit("https://hard.rozetka.com.ua/ua/592071073/p592071073/", exact_title),
            hit("https://hard.rozetka.com.ua/592071073/p592071073/", exact_title, position=2),
            hit("https://hard.rozetka.com.ua/monitors/c80089/producer=xiaomi/", exact_title, position=3),
        ],
        "prom.ua": [
            hit("https://prom.ua/m5380328037794579431-monitor-redmi-a27q.html", exact_title),
            hit("https://prom.ua/ua/m5058408590680385516-monitor-xiaomi-redmi.html", exact_title, position=2),
            hit("https://prom.ua/Monitor-100gts.html", exact_title, position=3),
        ],
        "epicentrk.ua": [
            hit("https://epicentrk.ua/ua/shop/mplc-monitor-redmi-a27q-2025-p27qcb-ra.html", exact_title),
        ],
        "hotline.ua": [
            hit("https://hotline.ua/ua/computer-monitory/xiaomi-a27q-2025-p27qcb-ra/", "Xiaomi A27Q 2025 (P27QCB-RA)"),
        ],
        "__other__": [],
    }
    logs = []
    prepared = _prepare_candidates(ROW, grouped, MARKETS, {"verify_candidates_per_marketplace": 8}, logs.append)
    assert len(prepared["rozetka.com.ua"]) == 1
    assert len(prepared["prom.ua"]) == 2
    assert len(prepared["epicentrk.ua"]) == 1
    assert len(prepared["hotline.ua"]) == 1
