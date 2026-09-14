import json
import time
import re
import statistics
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


def _median_price(items):
    vals = []
    for x in items:
        try:
            v = float(x.get("price"))
            if v > 0:
                vals.append(v)
        except (TypeError, ValueError):
            pass
    return statistics.median(vals) if vals else None


def _balanced_market_offers(accepted_market, accepted_other):
    """Return one representative price per independent market source.

    Main marketplaces are one source each; every independent other-UA host is
    another source. Multiple listings from one source are collapsed to the
    median so one marketplace cannot dominate the market statistics.
    """
    groups = {}
    for x in accepted_market:
        key = ("marketplace", x.get("marketplace") or "")
        groups.setdefault(key, []).append(x)
    for x in accepted_other:
        key = ("other", x.get("host") or x.get("url") or "")
        groups.setdefault(key, []).append(x)

    reps = []
    for (kind, name), items in groups.items():
        med = _median_price(items)
        if med is None:
            continue
        reps.append({
            "price": med,
            "marketplace": name if kind == "marketplace" else "Інші магазини",
            "host": name if kind == "other" else "",
            "source_kind": kind,
            "source_name": name,
        })
    return reps


def _clean_title_for_search(title, brand="", max_words=8):
    text = str(title or "")
    # Remove bracketed supplier/model duplicates and noisy punctuation.
    text = re.sub(r"\([^)]{0,80}\)", " ", text)
    text = re.sub(r"\[[^]]{0,80}\]", " ", text)
    text = re.sub(r"[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ+._-]+", " ", text)
    words = [w for w in text.split() if len(w) > 1]
    # Avoid duplicating brand if it is already in the title.
    result = " ".join(words[:max_words]).strip()
    return result


def _cascade_queries(row, primary_query, max_queries=3):
    sku = str(row.get("Артикул") or "").strip()
    brand = str(row.get("Производитель") or "").strip()
    title = _clean_title_for_search(row.get("Название") or "")
    queries = []

    def add(q):
        q = " ".join(str(q or "").split()).strip()
        if q and q.lower() not in {x.lower() for x in queries}:
            queries.append(q)

    # Stage 1: identifier only — cheapest and most precise.
    add(sku or primary_query)
    # Stage 2: brand + SKU/model.
    if brand and sku:
        add(f"{brand} {sku}")
    # Stage 3: brand/title or clean title.
    if title:
        if brand and brand.lower() not in title.lower():
            add(f"{brand} {title}")
        else:
            add(title)

    return queries[:max(1, int(max_queries))]


def _merge_grouped_hits(target, incoming, domains, limit_per_domain, other_limit=8):
    for domain in domains:
        current = target.setdefault(domain, [])
        seen = {x.get("url") for x in current}
        for hit in incoming.get(domain, []):
            url = hit.get("url")
            if not url or url in seen:
                continue
            current.append(hit)
            seen.add(url)
            if len(current) >= limit_per_domain:
                break

    other_current = target.setdefault("__other__", [])
    other_seen = {x.get("url") for x in other_current if x.get("url")}
    for hit in incoming.get("__other__", []):
        url = hit.get("url")
        if not url or url in other_seen:
            continue
        other_current.append(hit)
        other_seen.add(url)
        if len(other_current) >= other_limit:
            break
    return target


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
        accepted_other = []
        suspicious_other = []
        domains = [m["domain"] for m in market_cfg]

        grouped_hits = {d: [] for d in domains}
        grouped_hits["__other__"] = []
        cascade_queries = _cascade_queries(
            row, q, max_queries=cfg.get("cascade_max_queries", 3)
        )
        min_hits = int(cfg.get("cascade_min_hits", 3))
        cascade_enabled = bool(cfg.get("cascade_search_enabled", True))

        log(f"CASCADE PLAN: {cascade_queries} min_hits={min_hits} enabled={cascade_enabled}")

        for stage, search_query in enumerate(cascade_queries, 1):
            if stage > 1 and not cascade_enabled:
                log("CASCADE STOP: disabled in config")
                break

            current_hits = sum(len(grouped_hits.get(d, [])) for d in domains)
            if stage > 1 and current_hits >= min_hits:
                log(f"CASCADE STOP: already have {current_hits} unique marketplace hit(s)")
                break

            log(f"SEARCH STAGE {stage}/{len(cascade_queries)}: {search_query}")
            try:
                stage_hits = searcher.search_all(
                    search_query,
                    domains,
                    limit_per_domain=cfg["max_results_per_marketplace"],
                    exact_query=True,
                )
                _merge_grouped_hits(
                    grouped_hits,
                    stage_hits,
                    domains,
                    cfg["max_results_per_marketplace"],
                    cfg.get("other_ua_shops_max_hits", 8),
                )
                total_unique = sum(len(grouped_hits.get(d, [])) for d in domains)
                other_unique = len(grouped_hits.get("__other__", []))
                log(f"SEARCH STAGE {stage} RESULT: target_hits={total_unique} other_ua_hits={other_unique}")
            except Exception as e:
                log(f"SERPER STAGE {stage} ERROR {type(e).__name__}: {e}")


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
                    "Магазин": "",
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

        # v0.7: analyze Ukrainian shops found in the SAME Serper responses.
        # These prices are shown separately and DO NOT affect marketplace statistics,
        # score or verdict until we validate the new source on real data.
        other_hits = grouped_hits.get("__other__", [])
        log(f"OTHER UA SHOPS: hits={len(other_hits)}")
        for n, hit in enumerate(other_hits, 1):
            if cancel_cb and cancel_cb():
                canceled = True
                log("CANCEL requested during other-shop scan")
                break

            url = hit.get("url") or ""
            hit_title = hit.get("title") or ""
            host = hit.get("host") or ""
            price_hint = hit.get("price_hint")
            pre_match = score_match(row, hit_title, url)
            log(f"  OTHER HIT {n}: host={host} title={hit_title[:120]} | {url}")

            html = cache.get(url, cfg.get("page_cache_seconds", 86400))
            prod = None
            blocked = False
            if html is None:
                try:
                    time.sleep(cfg["request_delay_seconds"])
                    rr = sess.get(url, timeout=25, allow_redirects=True)
                    log(f"  OTHER FETCH: HTTP {rr.status_code} final={rr.url} len={len(rr.text)}")
                    if rr.status_code >= 400:
                        blocked = True
                    else:
                        html = rr.text
                        cache.put(url, html)
                except Exception as e:
                    log(f"  OTHER FETCH ERROR {type(e).__name__}: {e}")
                    blocked = True
            else:
                log(f"  OTHER CACHE: page hit len={len(html)}")

            if html:
                try:
                    prod = extract_product(html, url)
                except Exception as e:
                    log(f"  OTHER EXTRACT ERROR {type(e).__name__}: {e}")

            candidate_title = (prod or {}).get("title") or hit_title
            match = score_match(row, candidate_title, url)
            extracted_price = (prod or {}).get("price")
            chosen_price = extracted_price
            price_source = "page"

            if not chosen_price and price_hint and match >= cfg.get("search_price_match_threshold", 90):
                chosen_price = price_hint
                price_source = "serper"
                log(f"  OTHER FALLBACK PRICE: {chosen_price} from Serper (blocked={blocked})")

            if match < cfg["match_threshold"]:
                log(f"  OTHER REJECT: match<{cfg['match_threshold']}")
                continue
            if not chosen_price:
                log("  OTHER REJECT: no price")
                continue

            price_status = "ПІДТВЕРДЖЕНА"
            price_reason = ""
            suspicious = False
            try:
                own_num = float(row.get("Цена")) if row.get("Цена") not in (None, "", 0) else None
                cand_num = float(chosen_price)
                ratio_limit = float(cfg.get("serper_price_ratio_limit", 3.0))
                if price_source == "serper" and own_num and cand_num > 0:
                    ratio = max(cand_num / own_num, own_num / cand_num)
                    if ratio > ratio_limit:
                        suspicious = True
                        price_status = "⚠️ ЦІНА НЕ ПІДТВЕРДЖЕНА"
                        price_reason = f"Serper fallback differs from own price by {ratio:.2f}x (> {ratio_limit:.2f}x)"
            except (TypeError, ValueError, ZeroDivisionError):
                pass

            final_other = {
                "title": candidate_title,
                "price": chosen_price,
                "url": url,
                "host": host,
                "marketplace": "Інші магазини",
                "match_score": round(match, 1),
                "price_source": price_source,
            }
            offer_rows.append({
                "Код товара": row["Код товара"],
                "Категория": row.get("Категория", ""),
                "Постачальник": supplier,
                "Артикул": row["Артикул"],
                "Маркетплейс": "Інші магазини",
                "Магазин": host,
                "Название конкурента": candidate_title,
                "Цена конкурента": chosen_price,
                "Источник цены": price_source,
                "Статус цены": price_status,
                "Причина проверки": price_reason,
                "Match %": round(match, 1),
                "URL": url,
            })

            if suspicious:
                suspicious_other.append(final_other)
                log(f"  OTHER SUSPICIOUS: {host} price={chosen_price} -> excluded")
                continue

            accepted_other.append(final_other)
            log(f"  OTHER ACCEPT: {host} price={chosen_price} source={price_source} match={match:.1f}")

        # v0.8 BALANCED MARKET: one representative median price per independent
        # marketplace/host. This prevents 5 Prom listings from outweighing one
        # Rozetka listing, while validated other-UA shops can now influence the
        # market statistics and verdict.
        balanced_offers = _balanced_market_offers(accepted, accepted_other)
        st = stats(balanced_offers, row.get("Цена"))

        all_suspicious = suspicious_prices + suspicious_other
        if not balanced_offers and all_suspicious:
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

        # Count competitor offers with the same price as ours across the whole
        # validated market (main marketplaces + other UA shops).
        same_price_count = 0
        raw_valid_offers = accepted + accepted_other
        try:
            own_price_num = float(row.get("Цена")) if row.get("Цена") not in (None, "") else None
            if own_price_num is not None:
                same_price_count = sum(
                    1 for x in raw_valid_offers
                    if x.get("price") is not None
                    and abs(float(x["price"]) - own_price_num) <= float(cfg.get("same_price_tolerance_uah", 1.0))
                )
        except (TypeError, ValueError):
            same_price_count = 0

        sellers_found = len(raw_valid_offers)
        market_sources = len(balanced_offers)
        if market_sources >= 4:
            market_confidence = "Висока"
        elif market_sources >= 2:
            market_confidence = "Середня"
        elif market_sources == 1:
            market_confidence = "Низька"
        else:
            market_confidence = "Немає даних"

        # Do not issue the strongest recommendation from only one independent source.
        if market_sources == 1 and st.get("verdict") == "🔥 РЕКЛАМУВАТИ":
            st["verdict"] = "🟡 ТЕСТУВАТИ"

        log(
            f"PRODUCT RESULT: accepted={len(accepted)} suspicious={len(suspicious_prices)} "
            f"other_accepted={len(accepted_other)} other_suspicious={len(suspicious_other)} "
            f"balanced_sources={market_sources} same_price={same_price_count} min={st['min_price']} median={st['median']} "
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
            "Пропозицій": sellers_found,
            "Джерел ринку": market_sources,
        }
        for mp in market_cfg:
            report_row[mp["name"]] = marketplace_prices.get(mp["name"], "")

        other_prices = " / ".join(
            f"{float(x['price']):.2f}".rstrip("0").rstrip(".")
            for x in accepted_other if x.get("price") is not None
        )
        other_shops = " / ".join(
            f"{x.get('host','')}: {float(x['price']):.2f}".rstrip("0").rstrip(".")
            for x in accepted_other if x.get("price") is not None
        )

        report_row.update({
            "Інші магазини": other_prices,
            "Магазини": other_shops,
            "Пропозицій інших магазинів": len(accepted_other),
            "Найдено продавців": sellers_found,
            "= моїй ціні": same_price_count,
            "Достовірність": market_confidence,
            "Підозрілих цін": len(all_suspicious),
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
        "🟢 ПЕРСПЕКТИВНИЙ": 1,
        "🟡 ТЕСТУВАТИ": 2,
        "⚠️ ЦІНА НЕ ПІДТВЕРДЖЕНА": 3,
        "🔴 НЕ РЕКЛАМУВАТИ": 4,
        "⚪ НЕ ЗНАЙДЕНО": 5,
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
        "Маркетплейс", "Магазин", "Название конкурента",
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

    serper_usd_per_1000 = float(cfg.get("serper_usd_per_1000", 1.0))
    serper_cost_usd = round(searcher.api_requests * serper_usd_per_1000 / 1000.0, 4)
    api_per_product = round(searcher.api_requests / len(results), 3) if results else 0
    log(
        f"DONE products={len(results)} offers={len(offer_rows)} verdicts={counts} "
        f"serper_api_requests={searcher.api_requests} serper_cache_hits={searcher.cache_hits} "
        f"serper_cost_usd={serper_cost_usd:.4f} api_per_product={api_per_product} canceled={canceled}"
    )
    return {
        "products": len(results),
        "offers": len(offer_rows),
        "verdicts": counts,
        "serper_api_requests": searcher.api_requests,
        "serper_cache_hits": searcher.cache_hits,
        "serper_cost_usd": serper_cost_usd,
        "serper_usd_per_1000": serper_usd_per_1000,
        "api_per_product": api_per_product,
        "canceled": canceled,
    }
