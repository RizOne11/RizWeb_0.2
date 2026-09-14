import csv
from pathlib import Path
import xlsxwriter

VERDICT_COLORS = {
    "🔥 РЕКЛАМУВАТИ": ("#123B2A", "#7CF5B5"),
    "🟡 ТЕСТУВАТИ": ("#3A3213", "#FFD76A"),
    "⚠️ ЦІНА НЕ ПІДТВЕРДЖЕНА": ("#3A2B13", "#FFB85C"),
    "🔴 НЕ РЕКЛАМУВАТИ": ("#3B171B", "#FF7B86"),
    "⚪ НЕ ЗНАЙДЕНО": ("#263142", "#D8DEE8"),
}

def _number(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(" ", "").replace(",", "."))
    except ValueError:
        return None

def build_xlsx(csv_path, xlsx_path):
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    headers = list(rows[0].keys()) if rows else []

    wb = xlsxwriter.Workbook(str(xlsx_path))
    ws = wb.add_worksheet("Результат")
    ws.hide_gridlines(2)
    ws.freeze_panes(1, 0)

    header = wb.add_format({
        "bold": True, "font_color": "#AEB9C8", "bg_color": "#151F2D",
        "border": 1, "border_color": "#263142", "text_wrap": True,
        "valign": "vcenter"
    })
    text = wb.add_format({
        "font_color": "#F5F7FB", "bg_color": "#0E151F",
        "border": 1, "border_color": "#202A39", "valign": "vcenter"
    })
    wrap = wb.add_format({
        "font_color": "#F5F7FB", "bg_color": "#0E151F",
        "border": 1, "border_color": "#202A39", "text_wrap": True,
        "valign": "vcenter"
    })
    num = wb.add_format({
        "font_color": "#F5F7FB", "bg_color": "#0E151F",
        "border": 1, "border_color": "#202A39", "num_format": '#,##0.00',
        "valign": "vcenter"
    })
    pct = wb.add_format({
        "font_color": "#F5F7FB", "bg_color": "#0E151F",
        "border": 1, "border_color": "#202A39", "num_format": '0.00"%"',
        "valign": "vcenter"
    })

    for c, h in enumerate(headers):
        ws.write(0, c, h, header)

    numeric_headers = {"Твоя ціна","MIN","Медіана","Середня","MAX","Запас, грн","Score",
                       "Пропозицій","= моїй ціні","Підозрілих цін"}
    pct_headers = {"Запас, %"}

    for r_idx, row in enumerate(rows, 1):
        for c_idx, h in enumerate(headers):
            v = row.get(h, "")
            if h == "Вердикт":
                bg, fg = VERDICT_COLORS.get(v, ("#0E151F", "#F5F7FB"))
                fmt = wb.add_format({
                    "bold": True, "font_color": fg, "bg_color": bg,
                    "border": 1, "border_color": "#202A39", "valign": "vcenter"
                })
                ws.write(r_idx, c_idx, v, fmt)
            elif h in numeric_headers:
                n = _number(v)
                ws.write_number(r_idx, c_idx, n, num) if n is not None else ws.write_blank(r_idx, c_idx, None, num)
            elif h in pct_headers:
                n = _number(v)
                ws.write_number(r_idx, c_idx, n, pct) if n is not None else ws.write_blank(r_idx, c_idx, None, pct)
            elif h in {"Товар", "Категорія"} or h in {"Rozetka","Prom","Epicentr","Allo","Foxtrot","Comfy"}:
                ws.write(r_idx, c_idx, v, wrap)
            else:
                ws.write(r_idx, c_idx, v, text)

    widths = {
        "Вердикт": 25, "Товар": 42, "Категорія": 24, "Постачальник": 18,
        "Артикул": 20, "Твоя ціна": 13, "MIN": 12, "Медіана": 12,
        "Середня": 12, "MAX": 12, "Пропозицій": 12,
        "Rozetka": 20, "Prom": 24, "Epicentr": 20, "Allo": 20,
        "Foxtrot": 20, "Comfy": 20, "= моїй ціні": 13,
        "Підозрілих цін": 15, "Запас, грн": 13, "Запас, %": 12, "Score": 10,
    }
    for c, h in enumerate(headers):
        ws.set_column(c, c, widths.get(h, 16))
    ws.set_row(0, 34)
    for r in range(1, len(rows) + 1):
        ws.set_row(r, 42)

    if headers:
        ws.autofilter(0, 0, max(len(rows), 1), len(headers) - 1)

    wb.close()
