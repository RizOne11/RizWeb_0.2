from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

MARKET_COLUMNS = ["Rozetka", "Prom", "Epicentr", "Allo", "Foxtrot", "Comfy", "Kasta", "Hotline"]
SOURCE_TO_COLUMN = {"prom": "Prom", "epicentr": "Epicentr", "hotline": "Hotline"}
HEADERS = [
    "Вердикт", "Причина вердикту", "Товар", "Категорія", "Постачальник", "Артикул",
    "Стара ціна", "Знижка, %", "Твоя ціна", "MIN", "Медіана", "Середня", "MAX",
    "Пропозицій", "Джерел ринку", "Tier 1 перевірено", "Tier 1 знайдено", "Tier 1 статус",
    *MARKET_COLUMNS, "Інші магазини", "Магазини", "Пропозицій інших магазинів",
    "Найдено продавців", "За моєю ціною", "Достовірність", "Підозрілих цін",
    "Запас, грн", "Запас, %", "Score", "PriceIntel", "Автор"
]

def _num(value: Any) -> float | None:
    try:
        if value in (None, ""): return None
        return float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None

def _fmt_price(value: float | None) -> str:
    if value is None: return "НЕ ЗНАЙДЕНО"
    return f"{value:g}"

def _market_cells(offers: list[dict[str, Any]]) -> dict[str, str]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for o in offers:
        if o.get("price_status") == "SUSPICIOUS": continue
        p = _num(o.get("price"))
        if p is not None: grouped[o.get("source", "")].append(p)
    out = {name: "НЕ ПЕРЕВІРЯЛОСЬ" for name in MARKET_COLUMNS}
    for src, col in SOURCE_TO_COLUMN.items():
        prices = grouped.get(src, [])
        out[col] = ", ".join(_fmt_price(p) for p in sorted(set(prices))) if prices else "НЕ ЗНАЙДЕНО"
    return out

def _other_shops(offers: list[dict[str, Any]]) -> tuple[str, int, int]:
    rows = [o for o in offers if o.get("source") == "web_shops" and o.get("price_status") != "SUSPICIOUS"]
    grouped: dict[str, list[float]] = defaultdict(list)
    for o in rows:
        p = _num(o.get("price"))
        if p is not None: grouped[o.get("domain") or "web"].append(p)
    text = " | ".join(f"{domain}: {', '.join(_fmt_price(p) for p in sorted(set(prices)))}" for domain, prices in sorted(grouped.items()))
    return text or "НЕ ЗНАЙДЕНО", len(grouped), len(rows)

def _source_status(product: dict[str, Any]) -> tuple[str, str, str]:
    diagnostics = product.get("diagnostics") or {}
    selected = [x for x in ("prom", "epicentr", "hotline") if x in diagnostics]
    found = [x for x in selected if diagnostics.get(x, {}).get("accepted", 0) > 0]
    statuses = []
    for src in selected:
        d = diagnostics.get(src, {})
        health = str(d.get("health") or "NOT_FOUND")
        candidates = int(d.get("candidates", 0) or 0)
        accepted = int(d.get("accepted", 0) or 0)
        if accepted: state = "EXACT_FOUND"
        elif candidates: state = "CANDIDATES_REJECTED"
        else: state = health
        statuses.append(f"{src.title()}: {state}")
    return f"{len(selected)}/{len(selected)}" if selected else "0/0", f"{len(found)}/{len(selected)}" if selected else "0/0", " / ".join(statuses) or "Немає діагностики"

def _verdict(own: float | None, med: float | None, offers: int) -> tuple[str, str, float | None, float | None, int]:
    if offers <= 0 or med is None:
        return "⚪ НЕДОСТАТНЬО ДАНИХ", "MARKET_NOT_FOUND", None, None, 0
    if own is None:
        return "🟡 ПЕРЕВІРИТИ", "OWN_PRICE_MISSING", None, None, min(70, 30 + offers * 3)
    reserve = med - own
    reserve_pct = reserve / med * 100 if med else None
    if own <= med * 0.95:
        label, reason = "🟢 МОЖНА РЕКЛАМУВАТИ", "OWN_PRICE_BELOW_MARKET"
    elif own <= med * 1.05:
        label, reason = "🟡 ПЕРЕВІРИТИ", "OWN_PRICE_NEAR_MARKET"
    else:
        label, reason = "🔴 НЕ РЕКЛАМУВАТИ", "OWN_PRICE_ABOVE_MARKET"
    score = int(max(0, min(100, 50 + (reserve_pct or 0) * 2 + min(20, offers * 2))))
    return label, reason, round(reserve, 2), round(reserve_pct, 2) if reserve_pct is not None else None, score

def save_classic(products: list[dict[str, Any]], output: str, supplier: str = "") -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Результат"
    ws.append(["PUMA Platform v1.3"])
    ws.append(["Made by Пума (Чернявський А.)"])
    ws.append(HEADERS)
    for product in products:
        offers = product.get("offer_rows") or product.get("offers_detail") or []
        valid_offers = [o for o in offers if o.get("price_status") != "SUSPICIOUS"]
        own = _num(product.get("own_price"))
        mn = product.get("min_price")
        med = product.get("median_price")
        avg = product.get("avg_price")
        mx = product.get("max_price")
        market_cells = _market_cells(offers)
        other_text, other_domains, other_count = _other_shops(offers)
        tier_checked, tier_found, tier_status = _source_status(product)
        verdict = product.get("price_verdict") or "⚪ НЕ ЗНАЙДЕНО"
        reason = product.get("price_verdict_reason") or "NO_VALID_MARKET_OFFERS"
        reserve = product.get("reserve_uah")
        reserve_pct = product.get("reserve_pct")
        score = int(product.get("price_score") or 0)
        suspicious = int(product.get("suspicious_price_count") or 0)
        domains = {o.get("domain") or o.get("source") for o in valid_offers if o.get("domain") or o.get("source")}
        at_my_price = int(product.get("same_price_count") or 0)
        reliability = product.get("market_confidence") or "Немає даних"
        row = [
            verdict, reason, product.get("name", ""), product.get("category", ""), product.get("supplier") or supplier,
            product.get("article", ""), product.get("old_price", ""), product.get("discount", ""), own,
            mn, med, avg, mx, int(product.get("valid_offer_count") or len(valid_offers)), product.get("sources", 0), tier_checked, tier_found, tier_status,
            *[market_cells[name] for name in MARKET_COLUMNS], other_text, len(domains), other_count,
            int(product.get("valid_offer_count") or len(valid_offers)), at_my_price, reliability, suspicious, reserve, reserve_pct, score, "v1.3", "Пума (Чернявський А.)"
        ]
        ws.append(row)
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:{get_column_letter(len(HEADERS))}{ws.max_row}"
    ws.row_dimensions[1].height = 24
    ws["A1"].font = Font(size=16, bold=True, color="71F7B5")
    ws["A2"].font = Font(size=10, color="8D9AAB")
    header_fill = PatternFill("solid", fgColor="111824")
    for cell in ws[3]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in ws.iter_rows(min_row=4):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    widths = {1:22,2:28,3:48,4:24,5:18,6:16,18:42,27:42}
    for i in range(1, len(HEADERS)+1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(i, 15)
    about = wb.create_sheet("Про звіт")
    about.append(["PUMA Classic Report", "Додатковий аналітичний звіт. Основний детальний звіт не замінюється."])
    about.append(["Discovery", "Статуси джерел формуються з фактичної діагностики сканування; непідтримувані старі джерела позначені як НЕ ПЕРЕВІРЯЛОСЬ."])
    about.append(["Price Score", "Швидка детермінована оцінка позиції власної ціни відносно збалансованої медіани незалежних джерел. 100 = щонайменше 15% дешевше ринку; 50 = на рівні медіани; 0 = щонайменше 20% дорожче. Підозрілі цінові викиди не впливають на оцінку."])
    about.column_dimensions["A"].width = 24
    about.column_dimensions["B"].width = 100
    wb.save(output)
