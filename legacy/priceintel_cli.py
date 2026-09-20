import argparse
import os

from priceintel.runner import run_analysis


def main():
    """Compatibility wrapper for the historical python main.py CLI."""
    ap = argparse.ArgumentParser(description="Price Intelligence CLI compatibility wrapper")
    ap.add_argument("input_csv")
    ap.add_argument("--output", default="market_analysis.csv")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    if args.config:
        ap.error("--config is no longer supported by the legacy shim; use repository Config v2")

    detail = os.path.splitext(args.output)[0] + "_offers.csv"
    run_analysis(
        args.input_csv,
        args.output,
        detail,
        limit=max(1, int(args.limit)),
    )
    print("Saved:", args.output, "and", detail)


if __name__ == "__main__":
    main()
