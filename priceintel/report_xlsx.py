import csv
import json
from pathlib import Path
import xlsxwriter

BASE = Path(__file__).resolve().parents[1]

VERDICT_STYLE = {
    "🔥 РЕКЛАМУВАТИ": ("#123B2A", "#7CF5B5"),
    "🟢 ПЕРСПЕКТИВНИЙ": ("#173A30", "#8FF0C0"),
    "🟡 ТЕСТУВАТИ": ("#3A3213", "#FFD76A"),
    "⚠️ ЦІНА НЕ ПІДТВЕРДЖЕНА": ("#3A2B13", "#FFB85C"),
    "🔴 НЕ РЕКЛАМУВАТИ": ("#3B171B", "#FF7B86"),
    "⚪ НЕ ЗНАЙДЕНО": ("#263142", "#D8DEE8"),
}

def _num(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None

def _branding():
    try:
        cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    return (
        str(cfg.get("app_name", "PUMA Platform")),
        str(cfg.get("app_version", "v1.1")),
        str(cfg.get("brand_line", "Made by Пума (Чернявський А.)")),
    )

def build_xlsx(csv_path, xlsx_path):
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    headers = list(rows[0].keys()) if rows else []

    app_name, app_version, brand_line = _branding()

    wb = xlsxwriter.Workbook(str(xlsx_path))
    ws = wb.add_worksheet("Результат")
    ws.hide_gridlines(2)
    ws.freeze_panes(3, 0)

    title_fmt = wb.add_format({
        "bold": True, "font_color": "#71F7B5", "bg_color": "#0E151F",
        "font_size": 18, "align": "left", "valign": "vcenter"
    })
    brand_fmt = wb.add_format({
        "italic": True, "font_color": "#AEB9C8", "bg_color": "#0E151F",
        "font_size": 10, "align": "left", "valign": "vcenter"
    })
    header_fmt = wb.add_format({
        "bold": True, "font_color": "#C8D2E1", "bg_color": "#151F2D",
        "border": 1, "border_color": "#283446", "text_wrap": True,
        "valign": "vcenter", "align": "center"
    })
    text_fmt = wb.add_format({
        "font_color": "#F5F7FB", "bg_color": "#0E151F",
        "border": 1, "border_color": "#202A39", "valign": "vcenter"
    })
    wrap_fmt = wb.add_format({
        "font_color": "#F5F7FB", "bg_color": "#0E151F",
        "border": 1, "border_color": "#202A39", "valign": "vcenter",
        "text_wrap": True
    })
    num_fmt = wb.add_format({
        "font_color": "#F5F7FB", "bg_color": "#0E151F",
        "border": 1, "border_color": "#202A39", "valign": "vcenter",
        "num_format": '#,##0.00'
    })
    pct_fmt = wb.add_format({
        "font_color": "#F5F7FB", "bg_color": "#0E151F",
        "border": 1, "border_color": "#202A39", "valign": "vcenter",
        "num_format": '0.00"%"'
    })

    last_col = max(len(headers) - 1, 0)
    ws.merge_range(0, 0, 0, last_col, f"{app_name} {app_version}", title_fmt)
    ws.merge_range(1, 0, 1, last_col, brand_line, brand_fmt)

    header_row = 2
    for c, h in enumerate(headers):
        ws.write(header_row, c, h, header_fmt)

    number_cols = {
        "Стара ціна", "Твоя ціна", "MIN", "Медіана", "Середня", "MAX",
        "Пропозицій", "Джерел ринку", "Пропозицій інших магазинів",
        "Найдено продавців", "= моїй ціні", "Підозрілих цін",
        "Запас, грн", "Score"
    }
    market_cols = {
        "Rozetka", "Prom", "Epicentr", "Allo", "Foxtrot", "Comfy",
        "Kasta", "Hotline", "Інші магазини", "Магазини"
    }

    for r_idx, row in enumerate(rows, start=header_row + 1):
        for c_idx, h in enumerate(headers):
            value = row.get(h, "")
            if h == "Вердикт":
                bg, fg = VERDICT_STYLE.get(value, ("#0E151F", "#F5F7FB"))
                fmt = wb.add_format({
                    "bold": True, "font_color": fg, "bg_color": bg,
                    "border": 1, "border_color": "#202A39",
                    "valign": "vcenter"
                })
                ws.write(r_idx, c_idx, value, fmt)
            elif h in {"Запас, %", "Знижка, %"}:
                n = _num(value)
                if n is None:
                    ws.write_blank(r_idx, c_idx, None, pct_fmt)
                else:
                    ws.write_number(r_idx, c_idx, n, pct_fmt)
            elif h in number_cols:
                n = _num(value)
                if n is None:
                    ws.write_blank(r_idx, c_idx, None, num_fmt)
                else:
                    ws.write_number(r_idx, c_idx, n, num_fmt)
            elif h in market_cols or h in {"Товар", "Категорія", "Причина вердикту"}:
                ws.write(r_idx, c_idx, value, wrap_fmt)
            else:
                ws.write(r_idx, c_idx, value, text_fmt)

    widths = {
        "Вердикт": 25, "Причина вердикту": 31, "Товар": 42, "Категорія": 22,
        "Постачальник": 18, "Артикул": 20, "Стара ціна": 13, "Знижка, %": 12, "Твоя ціна": 13, "MIN": 12,
        "Медіана": 12, "Середня": 12, "MAX": 12, "Пропозицій": 12,
        "Джерел ринку": 13, "Rozetka": 20, "Prom": 24, "Epicentr": 20,
        "Allo": 20, "Foxtrot": 20, "Comfy": 20, "Kasta": 20, "Hotline": 24,
        "Інші магазини": 28, "Магазини": 48,
        "Пропозицій інших магазинів": 20, "Найдено продавців": 16,
        "= моїй ціні": 13, "Достовірність": 16, "Підозрілих цін": 15,
        "Запас, грн": 13, "Запас, %": 12, "Score": 10,
        "PriceIntel": 12, "Автор": 26,
    }
    for c, h in enumerate(headers):
        ws.set_column(c, c, widths.get(h, 16))

    ws.set_row(0, 28)
    ws.set_row(1, 20)
    ws.set_row(header_row, 34)
    for r in range(header_row + 1, header_row + 1 + len(rows)):
        ws.set_row(r, 42)

    if headers:
        ws.autofilter(header_row, 0, max(header_row + len(rows), header_row), len(headers) - 1)

    # Small metadata sheet so authorship/version survives even if columns are hidden later.
    meta = wb.add_worksheet("Про звіт")
    meta.hide_gridlines(2)
    meta.set_column(0, 0, 22)
    meta.set_column(1, 1, 48)
    meta.write(0, 0, "Продукт", header_fmt)
    meta.write(0, 1, f"{app_name} {app_version}", text_fmt)
    meta.write(1, 0, "Автор", header_fmt)
    meta.write(1, 1, brand_line, text_fmt)

    wb.close()
