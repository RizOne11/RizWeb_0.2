import json
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


def run_analysis(input_csv, output_csv, offers_csv, limit=30, marketplaces=None, progress_cb=None, log_cb=None):
    log = log_cb or (lambda msg: None)
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    selected = set(marketplaces or [m["name"] for m in cfg["marketplaces"]])
    market_cfg = [m for m in cfg["marketplaces"] if m["name"] in selected]
    rows = read_catalog(input_csv)
    if limit:
        rows = rows[:limit]

    log(f"START products={len(rows)} marketplaces={[m['name'] for m in market_cfg]}")
    searcher = DDGSearch(cfg["user_agent"], cfg["request_delay_seconds"], logger=log)
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": cfg["user_agent"],
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    })
    cache = Cache(str(Path(output_csv).with_name("priceintel_cache.sqlite")))
    results, offer_rows = [], []

    for i, row in enumerate(rows, 1):
        product_name = row.get("Название") or row.get("Артикул") or f"Товар {i}"
        q = build_query(row)
        log("=" * 72)
        log(f"PRODUCT {i}/{len(rows)}: {product_name}")
        log(f"SKU={row.get('Артикул','')} BRAND={row.get('Производитель','')} PRICE={row.get('Цена')}")
        log(f"QUERY: {q}")
        if progress_cb:
            progress_cb(i - 1, len(rows), product_name, f"Пошук: {product_name}")
        accepted = []
        for mp in market_cfg:
            log(f"MARKET {mp['name']} ({mp['domain']}): search begin")
            try:
                hits = searcher.search(q, mp["domain"], cfg["max_results_per_marketplace"])
            except Exception as e:
                log(f"MARKET {mp['name']}: SEARCH ERROR {type(e).__name__}: {e}")
                continue
            log(f"MARKET {mp['name']}: hits={len(hits)}")
            for n, hit in enumerate(hits, 1):
                url = hit["url"]
                log(f"  HIT {n}: {hit.get('title','')[:140]} | {url}")
                html = cache.get(url)
                if html is None:
                    try:
                        time.sleep(cfg["request_delay_seconds"])
                        rr = sess.get(url, timeout=25, allow_redirects=True)
                        log(f"  FETCH: HTTP {rr.status_code} final={rr.url} len={len(rr.text)}")
                        if rr.status_code >= 400:
                            continue
                        low = rr.text[:5000].lower()
                        if any(x in low for x in ["captcha", "verify you are human", "access denied", "cloudflare"]):
                            log("  FETCH: possible anti-bot/block page")
                        html = rr.text
                        cache.put(url, html)
                    except Exception as e:
                        log(f"  FETCH ERROR {type(e).__name__}: {e}")
                        continue
                else:
                    log(f"  CACHE: hit len={len(html)}")
                try:
                    prod = extract_product(html, url)
                except Exception as e:
                    log(f"  EXTRACT ERROR {type(e).__name__}: {e}")
                    continue
                candidate_title = prod.get("title") or hit.get("title") or ""
                match = score_match(row, candidate_title)
                log(f"  EXTRACT: title={candidate_title[:140]!r} price={prod.get('price')} match={match:.1f}")
                if match < cfg["match_threshold"]:
                    log(f"  REJECT: match<{cfg['match_threshold']}")
                    continue
                if not prod.get("price"):
                    log("  REJECT: no price extracted")
                    continue
                prod.update({"marketplace": mp["name"], "match_score": round(match, 1)})
                accepted.append(prod)
                offer_rows.append({
                    "Код товара": row["Код товара"], "Артикул": row["Артикул"],
                    "Маркетплейс": mp["name"], "Название конкурента": prod["title"],
                    "Цена конкурента": prod["price"], "Match %": round(match, 1), "URL": prod["url"]
                })
                log(f"  ACCEPT: {mp['name']} price={prod['price']} match={match:.1f}")
        st = stats(accepted, row.get("Цена"))
        log(f"PRODUCT RESULT: accepted={len(accepted)} min={st['min_price']} median={st['median']} score={st['price_score']} verdict={st['verdict']}")
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
    log(f"DONE products={len(results)} offers={len(offer_rows)} verdicts={counts}")
    return {"products": len(results), "offers": len(offer_rows), "verdicts": counts}
