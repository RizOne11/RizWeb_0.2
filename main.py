"""Backward-compatible entrypoint for the legacy PriceIntel CLI.

Production PUMA runs through durable_wsgi:app. The old CLI implementation lives
under legacy/priceintel_cli.py so imports and direct python main.py usage keep
working without mixing legacy code into the production runtime.
"""

from legacy.priceintel_cli import main


if __name__ == "__main__":
    main()
