import json
import time
import re
import statistics
import concurrent.futures
import os
from pathlib import Path
import requests

from .io import read_catalog, write_csv, discount_pct
from .matcher import build_query, score_match, classify_match, build_fingerprint
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


def _post_verify_price_outliers(accepted_market, accepted_other, own_price, offer_rows, cfg, log):
    """Second verification gate for obviously bad extracted prices.

    Product identity is checked first. This gate then looks for extraction/snippet
    anomalies (installment payment, accessory price, typo, etc.) using peer
    consensus. It never upgrades a weak product match and it does not spend any
    extra API credits. Outliers are moved to the suspicious pool and excluded
    from market statistics/verdicts, but remain visible in the offers audit.
    """
    enabled = bool(cfg.get("price_consensus_verification_enabled", True))
    if not enabled:
        return accepted_market, accepted_other, [], []

    ratio_limit = float(cfg.get("price_consensus_ratio_limit", 3.0))
    min_peer_refs = int(cfg.get("price_consensus_min_peer_refs", 2))
    all_items = [("market", x) for x in accepted_market] + [("other", x) for x in accepted_other]
    if len(all_items) < 2:
        return accepted_market, accepted_other, [], []

    own_num = None
    try:
        own_num = float(own_price) if own_price not in (None, "", 0) else None
    except (TypeError, ValueError):
        own_num = None

    suspicious_market, suspicious_other = [], []
    keep_market, keep_other = [], []

    for kind, item in all_items:
        try:
            price = float(item.get("price"))
        except (TypeError, ValueError):
            (keep_market if kind == "market" else keep_other).append(item)
            continue
        refs = []
        for _, peer in all_items:
            if peer is item:
                continue
            try:
                pv = float(peer.get("price"))
                if pv > 0:
                    refs.append(pv)
            except (TypeError, ValueError):
                pass
        if own_num and own_num > 0:
            refs.append(own_num)

        # Need at least two independent reference values before calling a price
        # anomalous. This keeps genuine extreme bargains from being rejected on
        # the basis of our own price alone.
        if len(refs) < min_peer_refs:
            (keep_market if kind == "market" else keep_other).append(item)
            continue

        ref = statistics.median(refs)
        if ref <= 0 or price <= 0:
            (keep_market if kind == "market" else keep_other).append(item)
            continue
        ratio = max(price / ref, ref / price)
        if ratio <= ratio_limit:
            (keep_market if kind == "market" else keep_other).append(item)
            continue

        reason = f"price consensus outlier {ratio:.2f}x vs peer median {ref:.2f} (> {ratio_limit:.2f}x)"
        item["price_verification_reason"] = reason
        if kind == "market":
            suspicious_market.append(item)
        else:
            suspicious_other.append(item)
        log(f"  PRICE VERIFY SUSPICIOUS: {item.get('marketplace') or item.get('host')} price={price} | {reason}")

        # Preserve the offer in the audit report, but explicitly show that it did
        # not affect market statistics. URL is our stable join key inside a run.
        url = item.get("url") or ""
        for audit in reversed(offer_rows):
            if url and audit.get("URL") == url:
                audit["Статус цены"] = "⚠️ АНОМАЛЬНА ЦІНА"
                audit["Причина проверки"] = reason
                break

    return keep_market, keep_other, suspicious_market, suspicious_other


def _resolve_verdict(st, own_price, market_sources, suspicious_count, cfg, log):
    """Return final verdict using an explicit market price-position guard."""
    base_verdict = st.get("verdict") or "⚪ НЕ ЗНАЙДЕНО"

    if not market_sources:
        if suspicious_count:
            return "⚠️ ЦІНА НЕ ПІДТВЕРДЖЕНА", "NO_VALID_OFFERS_SUSPICIOUS_ONLY"
        return "⚪ НЕ ЗНАЙДЕНО", "NO_VALID_MARKET_OFFERS"

    try:
        own_num = float(own_price) if own_price not in (None, "", 0) else None
        median_raw = st.get("median")
        median_num = float(median_raw) if median_raw not in (None, "", 0) else None
        threshold_pct = float(cfg.get("market_overprice_red_pct", 10.0))

        if own_num is not None and median_num is not None and median_num > 0:
            overprice_pct = ((own_num / median_num) - 1.0) * 100.0
            log(
                f"PRICE POSITION: own={own_num:.2f} market={median_num:.2f} "
                f"overprice={overprice_pct:.2f}% sources={market_sources} "
                f"red_threshold={threshold_pct:.2f}%"
            )

            if market_sources >= 2 and overprice_pct >= threshold_pct:
                st["price_score"] = min(int(st.get("price_score") or 0), 39)
                return (
                    "🔴 НЕ РЕКЛАМУВАТИ",
                    f"OWN_PRICE_{overprice_pct:.1f}%_ABOVE_MARKET",
                )
    except (TypeError, ValueError, ZeroDivisionError) as e:
        log(f"PRICE POSITION ERROR: {type(e).__name__}: {e}")

    if market_sources == 1 and base_verdict == "🔥 РЕКЛАМУВАТИ":
        return "🟡 ТЕСТУВАТИ", "ONLY_ONE_INDEPENDENT_SOURCE"

    return base_verdict, f"BASE_SCORE_{int(st.get('price_score') or 0)}"

def _clean_title_for_search(title, brand="", max_words=14):
    text = str(title or "")
    # Keep model punctuation (P27QCB-RA), remove only noisy brackets/punctuation.
    text = re.sub(r"\([^)]{0,80}\)", " ", text)
    text = re.sub(r"\[[^]]{0,80}\]", " ", text)
    text = re.sub(r"[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ+._/\-\"×]+", " ", text)
    words = [w for w in text.split() if len(w) > 1]
    return " ".join(words[:max_words]).strip()


def _public_model_tokens(row):
    """Return model-like public identifiers, strongest first.

    Supplier article is intentionally separate: many supplier SKUs are internal and
    must not be treated as manufacturer MPNs. We prefer mixed alpha-numeric tokens
    from the title/parameters such as P27QCB-RA, A27Q, JBLC50HIRED.
    """
    fp = build_fingerprint(row)
    out = []
    seen = set()
    for token in fp.get("models") or []:
        t = str(token or "").strip('()[]{} ,;:\"\'')
        c = re.sub(r"[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ]+", "", t).lower()
        if len(c) < 4:
            continue
        if not re.search(r"[A-Za-zА-Яа-яІіЇїЄєҐґ]", t) or not re.search(r"\d", t):
            continue
        # Exclude obvious dimensions/resolutions masquerading as model tokens.
        if re.fullmatch(r"\d{3,4}[xх×]\d{3,4}", t, re.I):
            continue
        if c in seen:
            continue
        seen.add(c)
        out.append(t)
    # Hyphenated/long identifiers are usually stronger MPNs than short family names.
    out.sort(key=lambda x: (0 if '-' in x else 1, -len(x)))
    return out


def _sku_query_variants(sku):
    sku = str(sku or "").strip()
    if not sku:
        return []
    vals = [sku]
    if sku.isdigit():
        stripped = sku.lstrip('0') or '0'
        if stripped != sku and len(stripped) >= 3:
            vals.append(stripped)
    return vals


def _search_matrix_queries(row, max_queries=8):
    """Quality-first query matrix shared by EVERY marketplace and broad UA search.

    Order matters: strong public model/MPN first, then supplier article variants,
    then model family/full title. We deliberately avoid spending all query slots on
    near-duplicate identifier queries.
    """
    brand = str(row.get("Производитель") or "").strip()
    title_raw = str(row.get("Название") or "").strip()
    title = _clean_title_for_search(title_raw, brand=brand)
    sku = str(row.get("Артикул") or "").strip()
    models = _public_model_tokens(row)
    queries = []

    def add(q):
        q = " ".join(str(q or "").split()).strip()
        if not q:
            return
        key = q.casefold()
        if key not in {x.casefold() for x in queries}:
            queries.append(q)

    # 1) Strongest public MPN/model. Example: P27QCB-RA.
    if models:
        add(f'"{models[0]}"')
        if brand:
            add(f'{brand} "{models[0]}"')

    # 2) Supplier article variants. Useful for copied supplier feeds, but matcher
    # still requires independent product identity evidence.
    for value in _sku_query_variants(sku):
        add(f'"{value}"')

    # 3) Human model family query catches marketplaces that hide MPN/SKU.
    clean_words = title.split()
    family_parts = clean_words[:6]
    if brand and not any(w.casefold() == brand.casefold() for w in family_parts):
        family_parts.insert(0, brand)
    add(" ".join(family_parts))

    # 4) Full clean/raw title for exact-name listings.
    add(title)
    add(title_raw)

    # 5) Secondary public model tokens (e.g. A27Q) as fallback.
    for model in models[1:3]:
        add(f'"{model}"')
        if brand:
            add(f'{brand} "{model}"')

    limit = max(1, int(max_queries))
    return queries[:limit]


def _canonical_hit_key(hit):
    return (hit.get("canonical_url") or hit.get("url") or "").strip()


def _merge_grouped_hits(target, incoming, domains, limit_per_domain, other_limit=12):
    for domain in domains:
        current = target.setdefault(domain, [])
        seen = {_canonical_hit_key(x) for x in current if _canonical_hit_key(x)}
        for hit in incoming.get(domain, []):
            key = _canonical_hit_key(hit)
            if not key or key in seen:
                continue
            current.append(hit)
            seen.add(key)
            if len(current) >= limit_per_domain:
                break

    other_current = target.setdefault("__other__", [])
    other_seen = {_canonical_hit_key(x) for x in other_current if _canonical_hit_key(x)}
    for hit in incoming.get("__other__", []):
        key = _canonical_hit_key(hit)
        if not key or key in other_seen:
            continue
        other_current.append(hit)
        other_seen.add(key)
        if len(other_current) >= other_limit:
            break
    return target


def _run_search_matrix(row, market_cfg, searcher, cfg, log):
    """Discover candidates for all configured marketplaces + Ukrainian shops.

    Phase A runs broad queries to discover both Tier-1 and Other-UA shops.
    Phase B runs the SAME identity query matrix against EVERY marketplace using
    site:domain, even if Phase A already found a hit. This is deliberate: one hit
    is not enough when a marketplace can have multiple sellers/prices.
    """
    domains = [m["domain"] for m in market_cfg]
    grouped = {d: [] for d in domains}
    grouped["__other__"] = []
    matrix = _search_matrix_queries(row, cfg.get("search_matrix_max_queries", 6))
    broad_limit = int(cfg.get("broad_search_matrix_max_queries", len(matrix)))
    target_limit = int(cfg.get("marketplace_search_matrix_max_queries", len(matrix)))
    max_per_domain = int(cfg.get("max_results_per_marketplace", 20))
    other_limit = int(cfg.get("other_ua_shops_max_hits", 80))

    log(f"SEARCH MATRIX: {matrix}")
    # A. Broad market discovery; every query can contribute Other-UA stores.
    for idx, query in enumerate(matrix[:max(1, broad_limit)], 1):
        try:
            hits = searcher.search_all(query, domains, limit_per_domain=max_per_domain, exact_query=True)
            _merge_grouped_hits(grouped, hits, domains, max_per_domain, other_limit)
            log(
                f"BROAD MATRIX {idx}: q={query!r} target_hits="
                f"{sum(len(grouped.get(d, [])) for d in domains)} other_ua={len(grouped['__other__'])}"
            )
        except Exception as e:
            log(f"BROAD MATRIX ERROR {idx}: {type(e).__name__}: {e}")

    # B. Deterministic marketplace recovery/expansion for EVERY source.
    marketplace_errors = set()
    run_all = bool(cfg.get("marketplace_search_matrix_run_all", True))
    min_pool = int(cfg.get("marketplace_candidate_pool_target", 5))
    min_queries_before_stop = int(cfg.get("marketplace_min_queries_before_stop", 2))
    for mp in market_cfg:
        name, domain = mp["name"], mp["domain"]
        log(f"MARKETPLACE MATRIX START: {name} ({domain}) existing={len(grouped.get(domain, []))}")
        executed = 0
        for idx, query in enumerate(matrix[:max(1, target_limit)], 1):
            if (not run_all and executed >= min_queries_before_stop and len(grouped.get(domain, [])) >= min_pool):
                log(f"MARKETPLACE MATRIX STOP: {name} candidate_pool={len(grouped.get(domain, []))}")
                break
            targeted_query = f"{query} site:{domain}"
            try:
                hits = searcher.search_all(targeted_query, [domain], limit_per_domain=max_per_domain, exact_query=True)
                # Targeted queries contribute ONLY their marketplace; Other-UA is
                # discovered by the broad phase to avoid cross-contamination.
                _merge_grouped_hits(
                    grouped,
                    {domain: hits.get(domain, []), "__other__": []},
                    domains,
                    max_per_domain,
                    other_limit,
                )
                executed += 1
                log(
                    f"MARKETPLACE MATRIX {name} {idx}: q={targeted_query!r} "
                    f"new_total={len(grouped.get(domain, []))}"
                )
            except Exception as e:
                marketplace_errors.add(name)
                log(f"MARKETPLACE MATRIX ERROR {name} {idx}: {type(e).__name__}: {e}")
        log(f"MARKETPLACE MATRIX DONE: {name} candidates={len(grouped.get(domain, []))}")

    return grouped, matrix, marketplace_errors


def _load_checkpoint(path, log):
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        log(
            f"RESUME CHECKPOINT: next_index={data.get('next_index', 0)} "
            f"results={len(data.get('results') or [])} offers={len(data.get('offer_rows') or [])}"
        )
        return data
    except Exception as e:
        log(f"CHECKPOINT READ ERROR {type(e).__name__}: {e}")
        return None


def _save_checkpoint(path, next_index, results, offer_rows, log, elapsed_seconds=0.0):
    if not path:
        return
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        payload = {
            "version": "v1.1",
            "next_index": int(next_index),
            "results": results,
            "offer_rows": offer_rows,
            "saved_at": time.time(),
            "elapsed_seconds": round(float(elapsed_seconds or 0.0), 3),
        }
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
        log(f"CHECKPOINT SAVED: next_index={next_index}")
    except Exception as e:
        log(f"CHECKPOINT WRITE ERROR {type(e).__name__}: {e}")


def _prefetch_pages(grouped_hits, cache, cfg, headers, log, cancel_cb=None):
    """Fetch uncached candidate pages concurrently, then let normal parsing use cache."""
    urls = []
    seen = set()
    for hits in grouped_hits.values():
        for hit in hits:
            url = hit.get("url")
            if url and url not in seen:
                seen.add(url)
                if cache.get(url, cfg.get("page_cache_seconds", 86400)) is None:
                    urls.append(url)

    if not urls:
        log("PREFETCH: all candidate pages already cached")
        return

    workers = max(1, int(cfg.get("page_fetch_workers", 6)))
    timeout = max(3.0, float(cfg.get("request_timeout_seconds", 12)))
    delay = max(0.0, float(cfg.get("request_delay_seconds", 0.0)))
    log(f"PREFETCH: urls={len(urls)} workers={workers} timeout={timeout:g}s")

    def fetch_one(url):
        if cancel_cb and cancel_cb():
            return url, "canceled", None
        try:
            if delay:
                time.sleep(delay)
            rr = requests.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )
            if rr.status_code >= 400:
                return url, f"http_{rr.status_code}", None
            html = rr.text
            low = html[:5000].lower()
            if any(x in low for x in ["captcha", "verify you are human", "access denied", "cloudflare"]):
                return url, "possible_block", html
            return url, "ok", html
        except Exception as e:
            return url, f"{type(e).__name__}", None

    ok = 0
    failed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fetch_one, url): url for url in urls}
        for fut in concurrent.futures.as_completed(futures):
            if cancel_cb and cancel_cb():
                for pending in futures:
                    pending.cancel()
                break
            url, status, html = fut.result()
            if html:
                try:
                    cache.put(url, html)
                    ok += 1
                except Exception as e:
                    failed += 1
                    log(f"PREFETCH CACHE ERROR {type(e).__name__}: {e}")
            else:
                failed += 1
            log(f"PREFETCH RESULT: {status} | {url[:140]}")
    log(f"PREFETCH DONE: cached={ok} failed={failed}")



def _candidate_source_count(grouped_hits, domains):
    """Count independent candidate sources before page validation.

    Each target marketplace counts once if it has at least one hit.
    Every unique Other-UA host counts once.
    """
    sources = 0
    for domain in domains:
        if grouped_hits.get(domain):
            sources += 1
    other_hosts = {
        (x.get("host") or "").strip().lower()
        for x in grouped_hits.get("__other__", [])
        if (x.get("host") or "").strip()
    }
    return sources + len(other_hosts)


def run_analysis(input_csv, output_csv, offers_csv, limit=30, marketplaces=None,
                 progress_cb=None, log_cb=None, cancel_cb=None, supplier="", checkpoint_path=None):
    log = log_cb or (lambda msg: None)
    run_started = time.perf_counter()
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    app_version = str(cfg.get("app_version", "v1.1"))
    brand_author = str(cfg.get("brand_author", "Пума (Чернявський А.)"))
    selected = set(marketplaces or [m["name"] for m in cfg["marketplaces"]])
    market_cfg = [m for m in cfg["marketplaces"] if m["name"] in selected]
    rows = read_catalog(input_csv, include_content=True, limit=limit)

    log(f"ENGINE {app_version} | START products={len(rows)} marketplaces={[m['name'] for m in market_cfg]}")

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

    checkpoint = _load_checkpoint(checkpoint_path, log)
    if checkpoint:
        results = list(checkpoint.get("results") or [])
        offer_rows = list(checkpoint.get("offer_rows") or [])
        start_index = max(0, min(int(checkpoint.get("next_index") or 0), len(rows)))
        prior_elapsed_seconds = float(checkpoint.get("elapsed_seconds") or 0.0)
    else:
        results, offer_rows = [], []
        start_index = 0
        prior_elapsed_seconds = 0.0
    canceled = False

    if start_index:
        log(f"RESUME: continuing from product {start_index + 1}/{len(rows)}")

    for i, row in enumerate(rows[start_index:], start_index + 1):
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

        grouped_hits, search_matrix, marketplace_search_errors = _run_search_matrix(
            row, market_cfg, searcher, cfg, log
        )

        deep_scan_enabled = bool(cfg.get("deep_scan_enabled", False))
        tier1_required = [
            x for x in cfg.get("tier1_required_marketplaces", [])
            if x in {m["name"] for m in market_cfg}
        ]
        tier1_status = {}
        by_name = {m["name"]: m for m in market_cfg}
        for mp_name in tier1_required:
            domain = by_name[mp_name]["domain"]
            if grouped_hits.get(domain):
                tier1_status[mp_name] = "CANDIDATES_FOUND"
            elif mp_name in marketplace_search_errors:
                tier1_status[mp_name] = "ERROR"
            else:
                tier1_status[mp_name] = "CHECKED_NOT_FOUND"
        tier1_errors = set(marketplace_search_errors)
        log(
            "SEARCH MATRIX SUMMARY: "
            + " | ".join(
                f"{m['name']}={len(grouped_hits.get(m['domain'], []))}" for m in market_cfg
            )
            + f" | other_ua={len(grouped_hits.get('__other__', []))}"
        )

        # v0.9 PERFORMANCE: fetch candidate pages in parallel into the shared cache.
        _prefetch_pages(
            grouped_hits,
            cache,
            cfg,
            dict(sess.headers),
            log,
            cancel_cb=cancel_cb,
        )

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
                        rr = sess.get(url, timeout=float(cfg.get("request_timeout_seconds", 12)), allow_redirects=True)
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
                match_info = classify_match(row, candidate_title, url, (prod or {}).get("description", ""))
                match = float(match_info["score"])
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

                if match_info["status"] not in set(cfg.get("accepted_match_statuses", ["EXACT"])):
                    log(f"  REJECT: product_match={match_info['status']} reason={match_info['reason']}")
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
                    "search_query": hit.get("search_query", ""),
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
                    "Match статус": match_info["status"],
                    "Match причина": match_info["reason"],
                    "Пошуковий запит": hit.get("search_query", ""),
                    "URL": final_prod["url"],
                    "PriceIntel": app_version,
                    "Автор": brand_author,
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
                    rr = sess.get(url, timeout=float(cfg.get("request_timeout_seconds", 12)), allow_redirects=True)
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
            match_info = classify_match(row, candidate_title, url, (prod or {}).get("description", ""))
            match = float(match_info["score"])
            extracted_price = (prod or {}).get("price")
            chosen_price = extracted_price
            price_source = "page"

            if not chosen_price and price_hint and match >= cfg.get("search_price_match_threshold", 90):
                chosen_price = price_hint
                price_source = "serper"
                log(f"  OTHER FALLBACK PRICE: {chosen_price} from Serper (blocked={blocked})")

            if match_info["status"] not in set(cfg.get("accepted_match_statuses", ["EXACT"])):
                log(f"  OTHER REJECT: product_match={match_info['status']} reason={match_info['reason']}")
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
                "search_query": hit.get("search_query", ""),
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
                "Match статус": match_info["status"],
                "Match причина": match_info["reason"],
                "Пошуковий запит": hit.get("search_query", ""),
                "URL": url,
                "PriceIntel": app_version,
                "Автор": brand_author,
            })

            if suspicious:
                suspicious_other.append(final_other)
                log(f"  OTHER SUSPICIOUS: {host} price={chosen_price} -> excluded")
                continue

            accepted_other.append(final_other)
            log(f"  OTHER ACCEPT: {host} price={chosen_price} source={price_source} match={match:.1f}")

        # v1.2.2 SECOND VERIFICATION GATE: after exact-product matching, remove
        # obvious price-extraction anomalies from market statistics without
        # spending additional Serper credits.
        accepted, accepted_other, post_suspicious_market, post_suspicious_other = _post_verify_price_outliers(
            accepted, accepted_other, row.get("Цена"), offer_rows, cfg, log
        )
        suspicious_prices.extend(post_suspicious_market)
        suspicious_other.extend(post_suspicious_other)

        # BALANCED MARKET: one representative median price per independent
        # marketplace/host. This prevents one marketplace with many listings from
        # dominating the market median.
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
                market_median_num = float(st["median"])
                market_reserve_uah = round(market_median_num - own_price_num, 2)
                # v0.8.1: express reserve against the market median.
                # Example: own 163998 vs market 104999 => about -56.19%.
                market_reserve_pct = round((market_reserve_uah / market_median_num) * 100, 2) if market_median_num else None
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

        # Final Tier-1 state is based on VERIFIED exact offers, not merely on
        # search candidates. This keeps "candidate found" distinct from
        # "exact competitor accepted".
        if deep_scan_enabled:
            for mp_name in tier1_required:
                domain = by_name[mp_name]["domain"]
                has_exact = any(x.get("marketplace") == mp_name for x in accepted)
                if has_exact:
                    tier1_status[mp_name] = "EXACT_FOUND"
                elif grouped_hits.get(domain):
                    tier1_status[mp_name] = "CANDIDATES_REJECTED"
                elif mp_name in marketplace_search_errors:
                    tier1_status[mp_name] = "ERROR"
                else:
                    tier1_status[mp_name] = "CHECKED_NOT_FOUND"
        tier1_checked = sum(1 for x in tier1_status.values() if x != "ERROR") if deep_scan_enabled else 0
        tier1_found = sum(1 for mp in tier1_required if marketplace_prices.get(mp)) if deep_scan_enabled else 0
        tier1_total = len(tier1_required) if deep_scan_enabled else 0
        tier1_complete = (tier1_total > 0 and tier1_checked == tier1_total) if deep_scan_enabled else True
        if deep_scan_enabled and not tier1_complete:
            market_confidence = "⚠️ Неповна перевірка Tier 1"
        elif market_sources >= 4:
            market_confidence = "Висока"
        elif market_sources >= 2:
            market_confidence = "Середня"
        elif market_sources == 1:
            market_confidence = "Низька"
        else:
            market_confidence = "Немає даних"

        # v0.8.2: resolve the final verdict once, after every market statistic
        # is known. Nothing below this point is allowed to overwrite it.
        final_verdict, verdict_reason = _resolve_verdict(
            st=st,
            own_price=row.get("Цена"),
            market_sources=market_sources,
            suspicious_count=len(all_suspicious),
            cfg=cfg,
            log=log,
        )
        if deep_scan_enabled and cfg.get("tier1_require_complete_for_hot_verdict", True) and not tier1_complete and str(final_verdict).startswith("🔥"):
            final_verdict = "⚠️ НЕПОВНА ПЕРЕВІРКА"
            verdict_reason = "TIER1_INCOMPLETE"
            log("VERDICT GUARD: HOT blocked because Tier 1 verification is incomplete")
        st["verdict"] = final_verdict
        log(f"FINAL VERDICT: {final_verdict} | reason={verdict_reason}")

        log(
            f"PRODUCT RESULT: accepted={len(accepted)} suspicious={len(suspicious_prices)} "
            f"other_accepted={len(accepted_other)} other_suspicious={len(suspicious_other)} "
            f"balanced_sources={market_sources} same_price={same_price_count} min={st['min_price']} median={st['median']} "
            f"reserve={market_reserve_uah} reserve_pct={market_reserve_pct} "
            f"score={st['price_score']} verdict={st['verdict']}"
        )

        report_row = {
            "Вердикт": st["verdict"],
            "Причина вердикту": verdict_reason,
            "Товар": row.get("Название", ""),
            "Категорія": row.get("Категория", ""),
            "Постачальник": supplier,
            "Артикул": row.get("Артикул", ""),
            "Стара ціна": row.get("Старая цена"),
            "Знижка, %": discount_pct(row),
            "Твоя ціна": row.get("Цена"),
            "MIN": st["min_price"],
            "Медіана": st["median"],
            "Середня": round(st["avg"], 2) if st["avg"] is not None else None,
            "MAX": st["max_price"],
            "Пропозицій": sellers_found,
            "Джерел ринку": market_sources,
            "Tier 1 перевірено": f"{tier1_checked}/{tier1_total}" if deep_scan_enabled else "",
            "Tier 1 знайдено": f"{tier1_found}/{tier1_total}" if deep_scan_enabled else "",
            "Tier 1 статус": " / ".join(f"{name}: {tier1_status.get(name, 'N/A')}" for name in tier1_required) if deep_scan_enabled else "",
        }
        for mp in market_cfg:
            value = marketplace_prices.get(mp["name"], "")
            if deep_scan_enabled and mp["name"] in tier1_required and not value:
                value = "ПОМИЛКА ПЕРЕВІРКИ" if tier1_status.get(mp["name"]) == "ERROR" else "НЕ ЗНАЙДЕНО"
            report_row[mp["name"]] = value

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
            "За моєю ціною": same_price_count,
            "Достовірність": market_confidence,
            "Підозрілих цін": len(all_suspicious),
            "Запас, грн": market_reserve_uah,
            "Запас, %": market_reserve_pct,
            "Score": st["price_score"],
            "PriceIntel": app_version,
            "Автор": brand_author,
        })
        results.append(report_row)

        # Persist only completed products. If the worker/browser dies, resume starts here.
        if not canceled:
            current_elapsed = prior_elapsed_seconds + (time.perf_counter() - run_started)
            _save_checkpoint(
                checkpoint_path, i, results, offer_rows, log,
                elapsed_seconds=current_elapsed,
            )

        if progress_cb:
            progress_cb(i, len(rows), product_name, f"Оброблено {i} з {len(rows)}")

        if canceled:
            break

    if not canceled and checkpoint_path:
        try:
            Path(checkpoint_path).unlink(missing_ok=True)
            log("CHECKPOINT CLEARED: analysis completed")
        except Exception as e:
            log(f"CHECKPOINT CLEAR ERROR {type(e).__name__}: {e}")

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
        "Причина проверки", "Match %", "Match статус", "Match причина",
        "URL", "PriceIntel", "Автор",
    ]
    # v1.2.1 safety guard: if Deep Scan adds another audit field later,
    # do not crash after a completed analysis. Preserve it in the CSV instead.
    for offer in offer_rows:
        for key in offer.keys():
            if key not in offer_fields:
                offer_fields.append(key)
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

    elapsed_seconds = round(
        prior_elapsed_seconds + (time.perf_counter() - run_started), 2
    )
    products_per_minute = round(
        len(results) / (elapsed_seconds / 60.0), 2
    ) if elapsed_seconds > 0 and results else 0.0
    found_products = sum(
        1 for r in results if int(float(r.get("Джерел ринку") or 0)) > 0
    )
    found_pct = round(found_products / len(results) * 100.0, 1) if results else 0.0
    source_values = [
        float(r.get("Джерел ринку") or 0) for r in results
    ]
    avg_market_sources = round(
        sum(source_values) / len(source_values), 2
    ) if source_values else 0.0
    serper_total_lookups = searcher.api_requests + searcher.cache_hits
    serper_cache_hit_pct = round(
        searcher.cache_hits / serper_total_lookups * 100.0, 1
    ) if serper_total_lookups else 0.0

    log(
        f"RELEASE METRICS: elapsed={elapsed_seconds:.2f}s "
        f"products_per_min={products_per_minute:.2f} "
        f"found={found_products}/{len(results)} ({found_pct:.1f}%) "
        f"avg_sources={avg_market_sources:.2f} "
        f"serper_cache_hit={serper_cache_hit_pct:.1f}%"
    )
    log(
        f"DONE products={len(results)} offers={len(offer_rows)} verdicts={counts} "
        f"serper_api_requests={searcher.api_requests} serper_cache_hits={searcher.cache_hits} "
        f"serper_cost_usd={serper_cost_usd:.4f} api_per_product={api_per_product} "
        f"elapsed_seconds={elapsed_seconds:.2f} canceled={canceled}"
    )
    return {
        "version": app_version,
        "author": brand_author,
        "products": len(results),
        "offers": len(offer_rows),
        "verdicts": counts,
        "serper_api_requests": searcher.api_requests,
        "serper_cache_hits": searcher.cache_hits,
        "serper_cache_hit_pct": serper_cache_hit_pct,
        "serper_cost_usd": serper_cost_usd,
        "serper_usd_per_1000": serper_usd_per_1000,
        "api_per_product": api_per_product,
        "elapsed_seconds": elapsed_seconds,
        "products_per_minute": products_per_minute,
        "found_products": found_products,
        "found_pct": found_pct,
        "avg_market_sources": avg_market_sources,
        "canceled": canceled,
    }
