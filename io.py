import csv
from pathlib import Path

CORE = ["Код товара", "Категория", "Артикул", "Название", "Цена", "Наличие", "Производитель"]

def detect_delimiter(path: str) -> str:
    sample = Path(path).read_text(encoding="utf-8-sig", errors="replace")[:5000]
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t,").delimiter
    except csv.Error:
        return ";"

def read_catalog(path: str):
    delim = detect_delimiter(path)
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delim)
        rows = []
        for r in reader:
            row = {k: (r.get(k) or "").strip() for k in CORE}
            try:
                row["Цена"] = float(str(row["Цена"]).replace(" ", "").replace(",", ".")) if row["Цена"] else None
            except ValueError:
                row["Цена"] = None
            rows.append(row)
    return rows

def write_csv(path: str, rows, fieldnames):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        w.writeheader()
        w.writerows(rows)
