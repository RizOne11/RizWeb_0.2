import os

from priceintel.search import _serper_safe_query, FirecrawlSearch
from priceintel.matcher import classify_match
from priceintel.extract import availability_state

ROW = {
    "Название": 'Монитор Xiaomi Redmi A27Q 2025 P27QCB-RA 2560x1440 2K IPS 100 Гц 27" Черный (2288)',
    "Производитель": "Xiaomi",
    "Артикул": "002288",
    "Параметры": [{"name": "Цвет", "value": "Черный"}],
}


def test_serper_free_safe_query_removes_operators_and_quotes():
    q = _serper_safe_query('"P27QCB-RA" site:hotline.ua -"123456"')
    assert q == "P27QCB-RA"


def test_firecrawl_can_be_disabled_without_key(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    fc = FirecrawlSearch(api_key="", allow_keyless=False)
    assert not fc.enabled


def test_gold_hotline_identity_is_exact_and_in_stock():
    title = "Xiaomi A27Q 2025 (P27QCB-RA) 27 IPS 2560x1440 100 Гц чорний"
    info = classify_match(ROW, title, "https://hotline.ua/ua/computer-monitory/xiaomi-a27q-2025-p27qcb-ra/", title)
    assert info["status"] == "EXACT"
    assert availability_state("Відвантаження зі складу завтра") == "IN_STOCK"


def test_gold_epicentr_identity_is_exact_and_in_stock():
    title = "Монітор Redmi A27Q 2025 P27QCB-RA 2560x1440 2K IPS 100 Гц 27 чорний"
    info = classify_match(ROW, title, "https://epicentrk.ua/ua/shop/example.html", title)
    assert info["status"] == "EXACT"
    assert availability_state("Готов к отправке") == "IN_STOCK"
