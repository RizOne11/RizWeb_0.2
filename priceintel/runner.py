import json
import os
import time
from pathlib import Path
import requests

from .io import read_catalog, write_csv
from .matcher import build_query, score_match
from .search import DDGSearch
from .extract import extract_product
from .cache import Cache
from .analyze import stats

BASE = Path(__file__).resolve().parents[1]


def run_analysis(input_csv, output_csv, offers_csv, limit=30, marketplaces=None, progress_cb=None):
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    selected = set(marketplaces or [m["name"] for m in cfg["marketplaces"]])
    market_cfg = [m for m in cfg["marketplaces"] if m["name"] in selected]
    rows = read_catalog(input_csv)
    if limit:
        rows = rows[:limit]

    searcher = DDGSearch(cfg["user_agent"], cfg["request_delay_seconds"])
    sess = requests.Session()
    sess.headers.update({"User-Agent": cfg["user_agent"], "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.7"})
    cache = Cache(str(Path(output_csv).with_name("priceintel_cache.sqlite")))
    results, offer_rows = [], []

    for i, row in enumerate(rows, 1):
        product_name = row.get("Название") or row.get("Артикул") or f"Товар {i}"
        if progress_cb:
            progress_cb(i - 1, len(rows), product_name, f"Пошук: {product_name}")
        q = build_query(row)
        accepted = []
        for mp in market_cfg:
            try:
                hits = searcher.search(q, mp["domain"], cfg["max_results_per_marketplace"])
            except Exception:
                continue
            for hit in hits:
                url = hit["url"]
                html = cache.get(url)
                if html is None:
                    try:
                        time.sleep(cfg["request_delay_seconds"])
                        rr = sess.get(url, timeout=20, allow_redirects=True)
                        rr.raise_for_status()
                        html = rr.text
                        cache.put(url, html)
                    except Exception:
                        continue
                prod = extract_product(html, url)
                match = score_match(row, prod["title"] or hit["title"])
                if match >= cfg["match_threshold"] and prod.get("price"):
                    prod.update({"marketplace": mp["name"], "match_score": round(match, 1)})
                    accepted.append(prod)
                    offer_rows.append({
                        "Код товара": row["Код товара"], "Артикул": row["Артикул"],
                        "Маркетплейс": mp["name"], "Название конкурента": prod["title"],
                        "Цена конкурента": prod["price"], "Match %": round(match, 1), "URL": prod["url"]
                    })
        st = stats(accepted, row.get("Цена"))
        results.append({**row, "Поисковый запрос": q, "Мин. рынка": st["min_price"],
                        "Медиана рынка": st["median"], "Средняя рынка": round(st["avg"], 2) if st["avg"] else None,
                        "Макс. рынка": st["max_price"], "Предложений": st["offers_count"],
                        "Разница с медианой %": round(st["delta_median_pct"], 2) if st["delta_median_pct"] is not None else None,
                        "Price Score": st["price_score"], "Вердикт": st["verdict"]})
        if progress_cb:
            progress_cb(i, len(rows), product_name, f"Оброблено {i} з {len(rows)}")

    fields = list(results[0].keys()) if results else []
    if results:
        write_csv(output_csv, results, fields)
    else:
        Path(output_csv).write_text("", encoding="utf-8-sig")
    if offer_rows:
        write_csv(offers_csv, offer_rows, list(offer_rows[0].keys()))
    else:
        Path(offers_csv).write_text("Код товара;Артикул;Маркетплейс;Название конкурента;Цена конкурента;Match %;URL\n", encoding="utf-8-sig")

    counts = {}
    for r in results:
        counts[r["Вердикт"]] = counts.get(r["Вердикт"], 0) + 1
    return {"products": len(results), "offers": len(offer_rows), "verdicts": counts}
