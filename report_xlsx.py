import csv
import xlsxwriter

VERDICT_STYLE = {
    "🔥 РЕКЛАМУВАТИ": ("#123B2A", "#7CF5B5"),
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

def build_xlsx(csv_path, xlsx_path):
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    headers = list(rows[0].keys()) if rows else []

    wb = xlsxwriter.Workbook(str(xlsx_path))
    ws = wb.add_worksheet("Результат")
    ws.hide_gridlines(2)
    ws.freeze_panes(1, 0)

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

    for c, h in enumerate(headers):
        ws.write(0, c, h, header_fmt)

    number_cols = {
        "Твоя ціна", "MIN", "Медіана", "Середня", "MAX",
        "Пропозицій", "Найдено продавців", "= моїй ціні", "Підозрілих цін",
        "Запас, грн", "Score"
    }
    market_cols = {"Rozetka", "Prom", "Epicentr", "Allo", "Foxtrot", "Comfy", "Kasta", "Hotline"}

    for r_idx, row in enumerate(rows, start=1):
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
            elif h == "Запас, %":
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
            elif h in market_cols or h in {"Товар", "Категорія"}:
                ws.write(r_idx, c_idx, value, wrap_fmt)
            else:
                ws.write(r_idx, c_idx, value, text_fmt)

    widths = {
        "Вердикт": 25, "Товар": 42, "Категорія": 22, "Постачальник": 18,
        "Артикул": 20, "Твоя ціна": 13, "MIN": 12, "Медіана": 12,
        "Середня": 12, "MAX": 12, "Пропозицій": 12,
        "Rozetka": 20, "Prom": 24, "Epicentr": 20, "Allo": 20,
        "Foxtrot": 20, "Comfy": 20, "Kasta": 20, "Hotline": 24,
        "Найдено продавців": 16, "= моїй ціні": 13, "Достовірність": 16,
        "Підозрілих цін": 15, "Запас, грн": 13, "Запас, %": 12,
        "Score": 10,
    }
    for c, h in enumerate(headers):
        ws.set_column(c, c, widths.get(h, 16))

    ws.set_row(0, 34)
    for r in range(1, len(rows) + 1):
        ws.set_row(r, 42)

    if headers:
        ws.autofilter(0, 0, max(len(rows), 1), len(headers) - 1)

    wb.close()
