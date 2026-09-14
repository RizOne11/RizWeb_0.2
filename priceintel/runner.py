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
                 progress_cb=None, log_cb=None, cancel_cb=None, supplier=""):
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
        log(f"SKU={row.get('Артикул','')} BRAND={row.get('Производитель','')} PRICE={row.get('Цена')} CATEGORY={row.get('Категория','')} SUPPLIER={supplier}")
        log(f"QUERY: {q}")
        if progress_cb:
            progress_cb(i - 1, len(rows), product_name, f"Пошук: {product_name}")

        accepted = []
        suspicious_prices = []
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

                # Price Validation v1:
                # Serper fallback prices are useful when a marketplace blocks us,
                # but snippets can contain installment/monthly-payment numbers.
                # If a Serper-only price differs from our own price by more than
                # the configured ratio, keep it in the offers report but EXCLUDE
                # it from market statistics and the final verdict.
                price_status = "ПІДТВЕРДЖЕНА"
                price_reason = ""
                own_price_num = None
                try:
                    own_price_num = float(row.get("Цена")) if row.get("Цена") not in (None, "", 0) else None
                except (TypeError, ValueError):
                    own_price_num = None

                ratio_limit = float(cfg.get("serper_price_ratio_limit", 3.0))
                suspicious = False
                if price_source == "serper" and own_price_num and chosen_price:
                    try:
                        candidate_price_num = float(chosen_price)
                        if candidate_price_num > 0:
                            ratio = max(candidate_price_num / own_price_num, own_price_num / candidate_price_num)
                            if ratio > ratio_limit:
                                suspicious = True
                                price_status = "⚠️ ЦІНА НЕ ПІДТВЕРДЖЕНА"
                                price_reason = f"Serper fallback differs from own price by {ratio:.2f}x (> {ratio_limit:.2f}x)"
                    except (TypeError, ValueError, ZeroDivisionError):
                        pass

                final_prod = {
                    "title": candidate_title,
                    "price": chosen_price,
                    "availability": (prod or {}).get("availability", ""),
                    "url": url,
                    "marketplace": mp["name"],
                    "match_score": round(match, 1),
                    "price_source": price_source,
                }

                offer_rows.append({
                    "Код товара": row["Код товара"],
                    "Категория": row.get("Категория", ""),
                    "Постачальник": supplier,
                    "Артикул": row["Артикул"],
                    "Маркетплейс": mp["name"],
                    "Название конкурента": final_prod["title"],
                    "Цена конкурента": final_prod["price"],
                    "Источник цены": price_source,
                    "Статус цены": price_status,
                    "Причина проверки": price_reason,
                    "Match %": round(match, 1),
                    "URL": final_prod["url"],
                })

                if suspicious:
                    suspicious_prices.append(final_prod)
                    log(
                        f"  SUSPICIOUS PRICE: {mp['name']} price={chosen_price} "
                        f"source={price_source} match={match:.1f} -> EXCLUDED FROM STATS"
                    )
                    continue

                accepted.append(final_prod)
                log(f"  ACCEPT: {mp['name']} price={chosen_price} source={price_source} match={match:.1f}")

            if canceled:
                break

        st = stats(accepted, row.get("Цена"))

        if not accepted and suspicious_prices:
            st["verdict"] = "⚠️ ЦІНА НЕ ПІДТВЕРДЖЕНА"

        own_price = row.get("Цена")
        market_reserve_uah = None
        market_reserve_pct = None
        if st["median"] is not None and own_price not in (None, "", 0):
            try:
                own_price_num = float(own_price)
                market_reserve_uah = round(float(st["median"]) - own_price_num, 2)
                market_reserve_pct = round((market_reserve_uah / own_price_num) * 100, 2) if own_price_num else None
            except (TypeError, ValueError):
                pass

        # Collect all VALID prices found per marketplace.
        marketplace_prices = {}
        for mp in market_cfg:
            prices = [
                float(x["price"]) for x in accepted
                if x.get("marketplace") == mp["name"] and x.get("price") is not None
            ]
            marketplace_prices[mp["name"]] = " / ".join(
                f"{p:.2f}".rstrip("0").rstrip(".") for p in prices
            )

        # Count competitor offers with exactly the same price as ours.
        same_price_count = 0
        try:
            own_price_num = float(row.get("Цена")) if row.get("Цена") not in (None, "") else None
            if own_price_num is not None:
                same_price_count = sum(
                    1 for x in accepted
                    if x.get("price") is not None
                    and abs(float(x["price"]) - own_price_num) < 0.01
                )
        except (TypeError, ValueError):
            same_price_count = 0

        log(
            f"PRODUCT RESULT: accepted={len(accepted)} suspicious={len(suspicious_prices)} "
            f"same_price={same_price_count} min={st['min_price']} median={st['median']} "
            f"reserve={market_reserve_uah} reserve_pct={market_reserve_pct} "
            f"score={st['price_score']} verdict={st['verdict']}"
        )

        report_row = {
            "Вердикт": st["verdict"],
            "Товар": row.get("Название", ""),
            "Категорія": row.get("Категория", ""),
            "Постачальник": supplier,
            "Артикул": row.get("Артикул", ""),
            "Твоя ціна": row.get("Цена"),
            "MIN": st["min_price"],
            "Медіана": st["median"],
            "Середня": round(st["avg"], 2) if st["avg"] is not None else None,
            "MAX": st["max_price"],
            "Пропозицій": st["offers_count"],
        }
        for mp in market_cfg:
            report_row[mp["name"]] = marketplace_prices.get(mp["name"], "")

        report_row.update({
            "= моїй ціні": same_price_count,
            "Підозрілих цін": len(suspicious_prices),
            "Запас, грн": market_reserve_uah,
            "Запас, %": market_reserve_pct,
            "Score": st["price_score"],
        })
        results.append(report_row)

        if progress_cb:
            progress_cb(i, len(rows), product_name, f"Оброблено {i} з {len(rows)}")

        if canceled:
            break

    verdict_order = {
        "🔥 РЕКЛАМУВАТИ": 0,
        "🟡 ТЕСТУВАТИ": 1,
        "⚠️ ЦІНА НЕ ПІДТВЕРДЖЕНА": 2,
        "🔴 НЕ РЕКЛАМУВАТИ": 3,
        "⚪ НЕ ЗНАЙДЕНО": 4,
    }
    results.sort(
        key=lambda r: (
            verdict_order.get(r.get("Вердикт"), 99),
            -(r.get("Score") or 0)
        )
    )

    fields = list(results[0].keys()) if results else []
    if results:
        write_csv(output_csv, results, fields)
    else:
        Path(output_csv).write_text("", encoding="utf-8-sig")

    offer_fields = [
        "Код товара", "Категория", "Постачальник", "Артикул",
        "Маркетплейс", "Название конкурента",
        "Цена конкурента", "Источник цены", "Статус цены",
        "Причина проверки", "Match %", "URL",
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
