import json
import time
from pathlib import Path
import requests

from .io import read_catalog, write_csv
from .matcher import build_query, score_match
from .search import SerperSearch
from .extract import extract_product
from .cache import Cache
from .analyze import stats

BASE = Path(__file__).resolve().parents[1]
DATA_DIR = BASE / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def run_analysis(input_csv, output_csv, offers_csv, limit=30, marketplaces=None,
                 progress_cb=None, log_cb=None, cancel_cb=None):
    log = log_cb or (lambda msg: None)
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    selected = set(marketplaces or [m["name"] for m in cfg["marketplaces"]])
    market_cfg = [m for m in cfg["marketplaces"] if m["name"] in selected]
    rows = read_catalog(input_csv)
    if limit:
        rows = rows[:limit]

    log(f"START products={len(rows)} marketplaces={[m['name'] for m in market_cfg]}")

    # Global cache reused by all jobs on the same Render instance.
    cache = Cache(str(DATA_DIR / "priceintel_global_cache.sqlite"))
    searcher = SerperSearch(
        logger=log,
        gl=cfg.get("search_gl", "ua"),
        hl=cfg.get("search_hl", "uk"),
        num=cfg.get("serper_num_results", 50),
        cache=cache,
        cache_ttl=cfg.get("serper_cache_seconds", 259200),
    )

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": cfg["user_agent"],
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    })

    results, offer_rows = [], []
    canceled = False

    for i, row in enumerate(rows, 1):
        if cancel_cb and cancel_cb():
            canceled = True
            log(f"CANCEL requested before product {i}/{len(rows)}")
            break

        product_name = row.get("Название") or row.get("Артикул") or f"Товар {i}"
        q = build_query(row)
        log("=" * 72)
        log(f"PRODUCT {i}/{len(rows)}: {product_name}")
        log(f"SKU={row.get('Артикул','')} BRAND={row.get('Производитель','')} PRICE={row.get('Цена')}")
        log(f"QUERY: {q}")
        if progress_cb:
            progress_cb(i - 1, len(rows), product_name, f"Пошук: {product_name}")

        accepted = []
        domains = [m["domain"] for m in market_cfg]

        try:
            grouped_hits = searcher.search_all(
                q,
                domains,
                limit_per_domain=cfg["max_results_per_marketplace"],
            )
        except Exception as e:
            log(f"SERPER FATAL {type(e).__name__}: {e}")
            grouped_hits = {d: [] for d in domains}

        for mp in market_cfg:
            if cancel_cb and cancel_cb():
                canceled = True
                log("CANCEL requested during marketplace scan")
                break

            hits = grouped_hits.get(mp["domain"], [])
            log(f"MARKET {mp['name']} ({mp['domain']}): hits={len(hits)}")

            for n, hit in enumerate(hits, 1):
                if cancel_cb and cancel_cb():
                    canceled = True
                    log("CANCEL requested during hit scan")
                    break

                url = hit["url"]
                hit_title = hit.get("title") or ""
                price_hint = hit.get("price_hint")
                pre_match = score_match(row, hit_title, url)
                log(f"  HIT {n}: {hit_title[:140]} | {url}")
                if price_hint:
                    log(f"  SEARCH PRICE HINT: {price_hint} pre_match={pre_match:.1f}")

                html = cache.get(url, cfg.get("page_cache_seconds", 86400))
                prod = None
                blocked = False

                if html is None:
                    try:
                        time.sleep(cfg["request_delay_seconds"])
                        rr = sess.get(url, timeout=25, allow_redirects=True)
                        log(f"  FETCH: HTTP {rr.status_code} final={rr.url} len={len(rr.text)}")
                        if rr.status_code >= 400:
                            blocked = True
                        else:
                            low = rr.text[:5000].lower()
                            if any(x in low for x in ["captcha", "verify you are human", "access denied", "cloudflare"]):
                                log("  FETCH: possible anti-bot/block page")
                            html = rr.text
                            cache.put(url, html)
                    except Exception as e:
                        log(f"  FETCH ERROR {type(e).__name__}: {e}")
                        blocked = True
                else:
                    log(f"  CACHE: page hit len={len(html)}")

                if html:
                    try:
                        prod = extract_product(html, url)
                    except Exception as e:
                        log(f"  EXTRACT ERROR {type(e).__name__}: {e}")

                candidate_title = (prod or {}).get("title") or hit_title
                match = score_match(row, candidate_title, url)
                extracted_price = (prod or {}).get("price")

                if prod:
                    log(f"  EXTRACT: title={candidate_title[:140]!r} price={extracted_price} match={match:.1f}")

                # Fallback: for blocked pages or pages without a parseable price,
                # use a Serper price hint only when product matching is strong.
                chosen_price = extracted_price
                price_source = "page"
                if not chosen_price and price_hint and match >= cfg.get("search_price_match_threshold", 90):
                    chosen_price = price_hint
                    price_source = "serper"
                    log(f"  FALLBACK PRICE: {chosen_price} from Serper (blocked={blocked})")

                if match < cfg["match_threshold"]:
                    log(f"  REJECT: match<{cfg['match_threshold']}")
                    continue
                if not chosen_price:
                    log("  REJECT: no price extracted or safe search-price hint")
                    continue

                final_prod = {
                    "title": candidate_title,
                    "price": chosen_price,
                    "availability": (prod or {}).get("availability", ""),
                    "url": url,
                    "marketplace": mp["name"],
                    "match_score": round(match, 1),
                    "price_source": price_source,
                }
                accepted.append(final_prod)
                offer_rows.append({
                    "Код товара": row["Код товара"],
                    "Артикул": row["Артикул"],
                    "Маркетплейс": mp["name"],
                    "Название конкурента": final_prod["title"],
                    "Цена конкурента": final_prod["price"],
                    "Источник цены": price_source,
                    "Match %": round(match, 1),
                    "URL": final_prod["url"],
                })
                log(f"  ACCEPT: {mp['name']} price={chosen_price} source={price_source} match={match:.1f}")

            if canceled:
                break

        st = stats(accepted, row.get("Цена"))
        log(f"PRODUCT RESULT: accepted={len(accepted)} min={st['min_price']} median={st['median']} score={st['price_score']} verdict={st['verdict']}")
        results.append({
            **row,
            "Поисковый запрос": q,
            "Мин. рынка": st["min_price"],
            "Медиана рынка": st["median"],
            "Средняя рынка": round(st["avg"], 2) if st["avg"] else None,
            "Макс. рынка": st["max_price"],
            "Предложений": st["offers_count"],
            "Разница с медианой %": round(st["delta_median_pct"], 2) if st["delta_median_pct"] is not None else None,
            "Price Score": st["price_score"],
            "Вердикт": st["verdict"],
        })

        if progress_cb:
            progress_cb(i, len(rows), product_name, f"Оброблено {i} з {len(rows)}")

        if canceled:
            break

    fields = list(results[0].keys()) if results else []
    if results:
        write_csv(output_csv, results, fields)
    else:
        Path(output_csv).write_text("", encoding="utf-8-sig")

    offer_fields = [
        "Код товара", "Артикул", "Маркетплейс", "Название конкурента",
        "Цена конкурента", "Источник цены", "Match %", "URL",
    ]
    if offer_rows:
        write_csv(offers_csv, offer_rows, offer_fields)
    else:
        Path(offers_csv).write_text(";".join(offer_fields) + "\n", encoding="utf-8-sig")

    counts = {}
    for r in results:
        counts[r["Вердикт"]] = counts.get(r["Вердикт"], 0) + 1

    log(
        f"DONE products={len(results)} offers={len(offer_rows)} verdicts={counts} "
        f"serper_api_requests={searcher.api_requests} serper_cache_hits={searcher.cache_hits} canceled={canceled}"
    )
    return {
        "products": len(results),
        "offers": len(offer_rows),
        "verdicts": counts,
        "serper_api_requests": searcher.api_requests,
        "serper_cache_hits": searcher.cache_hits,
        "canceled": canceled,
    }
