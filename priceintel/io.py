import csv
import html
import re
import xml.etree.ElementTree as ET
from pathlib import Path

CORE = [
    "Код товара", "Категория", "Артикул", "Название", "Цена",
    "Старая цена", "Наличие", "Производитель",
]

CONTENT_FIELDS = ["Описание", "Картинки", "Параметры", "Категория ID", "Валюта"]


def _num(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def detect_delimiter(path: str) -> str:
    sample = Path(path).read_text(encoding="utf-8-sig", errors="replace")[:5000]
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t,").delimiter
    except csv.Error:
        return ";"


def _clean_text(value):
    return (value or "").strip()


def _strip_html(text):
    text = html.unescape(str(text or ""))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(?:p|div|li|h[1-6])>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _read_csv_catalog(path: str, include_content=False, limit=None):
    delim = detect_delimiter(path)
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter=delim)
        try:
            headers = next(reader)
        except StopIteration:
            return rows

        # Duplicate headers (especially "Параметр") are intentionally preserved.
        index = {}
        for i, h in enumerate(headers):
            index.setdefault((h or "").strip(), []).append(i)

        def first(raw, name):
            pos = index.get(name, [])
            if not pos:
                return ""
            i = pos[0]
            return _clean_text(raw[i] if i < len(raw) else "")

        for raw in reader:
            row = {k: first(raw, k) for k in CORE}
            row["Цена"] = _num(row.get("Цена"))
            row["Старая цена"] = _num(row.get("Старая цена"))

            if include_content:
                params = []
                for i in index.get("Параметр", []):
                    value = _clean_text(raw[i] if i < len(raw) else "")
                    if value:
                        params.append(value)
                row.update({
                    "Описание": first(raw, "Описание"),
                    "Картинки": first(raw, "url картинки"),
                    "Параметры": params,
                    "Категория ID": "",
                    "Валюта": "UAH",
                })
            rows.append(row)
            if limit and len(rows) >= int(limit):
                break
    return rows


def _category_path(category_id, categories):
    if not category_id:
        return ""
    parts, seen = [], set()
    current = str(category_id)
    while current and current not in seen:
        seen.add(current)
        item = categories.get(current)
        if not item:
            break
        name, parent = item
        if name:
            parts.append(name)
        current = parent or ""
    return " / ".join(reversed(parts))


def _read_yml_catalog(path: str, include_content=False, limit=None):
    """Stream YML/XML offers into PriceIntel's canonical row schema.

    vendorCode is copied byte-for-byte as text into `Артикул` and is never
    translated or normalized. This is the platform's SKU Lock boundary.
    """
    categories = {}
    rows = []

    for event, elem in ET.iterparse(path, events=("end",)):
        tag = elem.tag.rsplit("}", 1)[-1]

        if tag == "category":
            cid = _clean_text(elem.attrib.get("id"))
            if cid:
                categories[cid] = (
                    _clean_text(elem.text),
                    _clean_text(elem.attrib.get("parentId")),
                )
            elem.clear()
            continue

        if tag != "offer":
            continue

        def text(name):
            child = elem.find(name)
            return _clean_text(child.text if child is not None else "")

        sku = text("vendorCode") or text("sku")
        category_id = text("categoryId")
        stock = text("stock_quantity")
        available = _clean_text(elem.attrib.get("available")).lower()
        availability = stock or ("1" if available in {"true", "1", "yes"} else "0")

        row = {
            "Код товара": _clean_text(elem.attrib.get("id")),
            "Категория": _category_path(category_id, categories),
            "Артикул": sku,  # SKU LOCK: exact supplier vendorCode
            "Название": text("name"),
            "Цена": _num(text("price")),
            "Старая цена": _num(text("oldprice")),
            "Наличие": availability,
            "Производитель": text("vendor"),
        }

        if include_content:
            desc_el = elem.find("description")
            description = "" if desc_el is None else "".join(desc_el.itertext()).strip()
            pictures = [
                _clean_text(x.text) for x in elem.findall("picture")
                if _clean_text(x.text)
            ]
            params = []
            for p in elem.findall("param"):
                value = _clean_text("".join(p.itertext()))
                if not value:
                    continue
                params.append({
                    "name": _clean_text(p.attrib.get("name")),
                    "value": value,
                    "id": _clean_text(p.attrib.get("id")),
                    "valueid": _clean_text(p.attrib.get("valueid")),
                })
            row.update({
                "Описание": description,
                "Описание текст": _strip_html(description),
                "Картинки": pictures,
                "Параметры": params,
                "Категория ID": category_id,
                "Валюта": text("currencyId") or "UAH",
            })

        rows.append(row)
        elem.clear()
        if limit and len(rows) >= int(limit):
            break

    return rows


def read_catalog(path: str, include_content=False, limit=None):
    suffix = Path(path).suffix.lower()
    if suffix in {".yml", ".xml"}:
        return _read_yml_catalog(path, include_content=include_content, limit=limit)
    return _read_csv_catalog(path, include_content=include_content, limit=limit)


def discount_pct(row):
    current = _num(row.get("Цена"))
    old = _num(row.get("Старая цена"))
    if current is None or old is None or old <= 0 or old <= current:
        return None
    return round((old - current) / old * 100.0, 2)


def write_csv(path: str, rows, fieldnames):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        w.writeheader()
        w.writerows(rows)
