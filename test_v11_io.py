from pathlib import Path
from priceintel.io import read_catalog, discount_pct


def run(yml_path=None, csv_path=None):
    if yml_path:
        rows = read_catalog(yml_path, include_content=True, limit=2)
        assert rows
        assert rows[0]["Артикул"] == "UDFHDH7S9SKFJ"
        assert rows[0]["Старая цена"] == 649.0
        assert discount_pct(rows[0]) == 31.43
        assert rows[0]["Картинки"]
        assert rows[0]["Параметры"]
    if csv_path:
        rows = read_catalog(csv_path, include_content=True, limit=2)
        assert rows
        assert rows[0]["Артикул"] == "UDFHDH7S9SKFJ"
        assert rows[0]["Старая цена"] == 649.0
        assert discount_pct(rows[0]) == 31.43
        assert discount_pct(rows[1]) is None
    print("v1.1 IO OK")


if __name__ == "__main__":
    import sys
    run(*(sys.argv[1:] + [None, None])[:2])
