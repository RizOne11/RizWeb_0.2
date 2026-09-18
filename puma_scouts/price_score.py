from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        number = float(str(value).replace(" ", "").replace(",", "."))
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def _currency_code(value: Any) -> str:
    text = str(value or "").strip().upper().replace(".", "")
    aliases = {
        "": "UAH", "UAH": "UAH", "ГРН": "UAH", "₴": "UAH", "HUA": "UAH",
        "USD": "USD", "$": "USD", "US$": "USD", "EUR": "EUR", "€": "EUR",
    }
    return aliases.get(text, text or "UAH")


def _independent_source_key(offer: dict[str, Any]) -> tuple[str, str]:
    source = str(offer.get("source") or "")
    if source == "web_shops":
        domain = str(offer.get("domain") or offer.get("url") or "web").casefold()
        return ("web", domain)
    return ("marketplace", source)


def _price_score(own_price: float | None, market_median: float | None) -> tuple[int, float | None]:
    """Legacy PUMA/Claude price-position score.

    100 at >=15% below market median, 50 at market median, 0 at >=20% above.
    Linear interpolation is used between those anchors.
    """
    if own_price is None or market_median is None or market_median <= 0:
        return 0, None
    delta = ((own_price - market_median) / market_median) * 100.0
    if delta <= -15:
        score = 100.0
    elif delta >= 20:
        score = 0.0
    elif delta <= 0:
        score = 50.0 + (-delta / 15.0) * 50.0
    else:
        score = 50.0 - (delta / 20.0) * 50.0
    return round(max(0.0, min(100.0, score))), delta


def _base_verdict(score: int) -> str:
    if score >= 85:
        return "🔥 РЕКЛАМУВАТИ"
    if score >= 65:
        return "🟢 ПЕРСПЕКТИВНИЙ"
    if score >= 40:
        return "🟡 ТЕСТУВАТИ"
    return "🔴 НЕ РЕКЛАМУВАТИ"


def assess_price_market(
    offers: list[dict[str, Any]],
    own_price: Any,
    *,
    outlier_ratio_limit: float = 3.0,
    min_peer_refs: int = 2,
    same_price_tolerance_uah: float = 1.0,
    market_overprice_red_pct: float = 10.0,
) -> dict[str, Any]:
    """Fast deterministic post-validation market assessment.

    No network/API work is performed here. Identity validation has already
    happened; this layer only evaluates the accepted UAH offers.
    """
    own = _num(own_price)
    priced: list[dict[str, Any]] = []
    for offer in offers:
        price = _num(offer.get("price"))
        currency = _currency_code(offer.get("currency"))
        if price is None or currency != "UAH":
            continue
        offer["price_status"] = "OK"
        offer["price_reason"] = ""
        priced.append(offer)

    suspicious: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for offer in priced:
        price = float(offer["price"])
        refs = [
            float(peer["price"])
            for peer in priced
            if peer is not offer and _num(peer.get("price")) is not None
        ]
        if own is not None:
            refs.append(own)

        if len(refs) >= min_peer_refs:
            ref = statistics.median(refs)
            if ref > 0:
                ratio = max(price / ref, ref / price)
                if ratio > outlier_ratio_limit:
                    reason = (
                        f"price consensus outlier {ratio:.2f}x vs peer median "
                        f"{ref:.2f} (> {outlier_ratio_limit:.2f}x)"
                    )
                    offer["price_status"] = "SUSPICIOUS"
                    offer["price_reason"] = reason
                    suspicious.append(offer)
                    continue
        kept.append(offer)

    groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    for offer in kept:
        price = _num(offer.get("price"))
        if price is not None:
            groups[_independent_source_key(offer)].append(price)

    representatives = []
    for (kind, name), values in groups.items():
        representatives.append(
            {
                "kind": kind,
                "name": name,
                "price": statistics.median(values),
                "offers": len(values),
            }
        )

    market_prices = [float(item["price"]) for item in representatives]
    market_sources = len(market_prices)
    if market_prices:
        market_min = min(market_prices)
        market_median = statistics.median(market_prices)
        market_avg = sum(market_prices) / len(market_prices)
        market_max = max(market_prices)
    else:
        market_min = market_median = market_avg = market_max = None

    score, delta_pct = _price_score(own, market_median)
    confirmed = sum(1 for o in kept if o.get("identity_confidence") == "CONFIRMED")
    probable = sum(1 for o in kept if o.get("identity_confidence") == "PROBABLE")
    has_confirmed = confirmed > 0

    if not market_prices:
        if suspicious:
            verdict = "⚠️ ЦІНА НЕ ПІДТВЕРДЖЕНА"
            reason = "NO_VALID_OFFERS_SUSPICIOUS_ONLY"
        else:
            verdict = "⚪ НЕ ЗНАЙДЕНО"
            reason = "NO_VALID_MARKET_OFFERS"
    elif own is None:
        verdict = "🟡 ТЕСТУВАТИ"
        reason = "OWN_PRICE_MISSING"
    else:
        verdict = _base_verdict(score)
        reason = f"BASE_PRICE_SCORE_{score}"

        if (
            market_sources >= 2
            and market_median
            and ((own / market_median) - 1.0) * 100.0 >= market_overprice_red_pct
        ):
            score = min(score, 39)
            verdict = "🔴 НЕ РЕКЛАМУВАТИ"
            reason = f"OWN_PRICE_{delta_pct:.1f}%_ABOVE_MARKET"
        elif market_sources == 1 and verdict == "🔥 РЕКЛАМУВАТИ":
            verdict = "🟡 ТЕСТУВАТИ"
            reason = "ONLY_ONE_INDEPENDENT_SOURCE"
        elif not has_confirmed and verdict in {"🔥 РЕКЛАМУВАТИ", "🟢 ПЕРСПЕКТИВНИЙ"}:
            verdict = "🟡 ТЕСТУВАТИ"
            reason = "NO_CONFIRMED_IDENTITY"

    reserve_uah = None
    reserve_pct = None
    if own is not None and market_median:
        reserve_uah = round(market_median - own, 2)
        reserve_pct = round((reserve_uah / market_median) * 100.0, 2)

    same_price_count = 0
    if own is not None:
        same_price_count = sum(
            1
            for offer in kept
            if _num(offer.get("price")) is not None
            and abs(float(offer["price"]) - own) <= same_price_tolerance_uah
        )

    if market_sources >= 4 and has_confirmed:
        confidence = "Висока"
    elif market_sources >= 2:
        confidence = "Середня"
    elif market_sources == 1:
        confidence = "Низька"
    else:
        confidence = "Немає даних"

    return {
        "price_score": score,
        "price_verdict": verdict,
        "price_verdict_reason": reason,
        "own_price_num": own,
        "delta_median_pct": round(delta_pct, 2) if delta_pct is not None else None,
        "market_min": market_min,
        "market_median": market_median,
        "market_avg": round(market_avg, 2) if market_avg is not None else None,
        "market_max": market_max,
        "market_sources": market_sources,
        "market_representatives": representatives,
        "market_confidence": confidence,
        "valid_offer_count": len(kept),
        "suspicious_price_count": len(suspicious),
        "reserve_uah": reserve_uah,
        "reserve_pct": reserve_pct,
        "same_price_count": same_price_count,
        "confirmed_offers": confirmed,
        "probable_offers": probable,
    }
