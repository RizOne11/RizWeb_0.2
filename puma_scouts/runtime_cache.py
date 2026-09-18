from __future__ import annotations

import os
import threading
from pathlib import Path

from priceintel.cache import Cache


_BASE = Path(__file__).resolve().parents[1]
_CACHE: Cache | None = None
_LOCK = threading.Lock()


def runtime_cache() -> Cache | None:
    """Shared lightweight cache for one PUMA web process.

    The old priceintel engine already had a proven SQLite cache. Reuse it instead
    of making every scout/product pay for the same Serper result or product page.
    Render's local disk is ephemeral, so this is an acceleration layer only;
    correctness never depends on it.
    """
    flag = os.getenv("PUMA_RUNTIME_CACHE_ENABLED", "1").strip().casefold()
    if flag in {"0", "false", "off", "no"}:
        return None

    global _CACHE
    if _CACHE is not None:
        return _CACHE
    with _LOCK:
        if _CACHE is None:
            path = Path(
                os.getenv(
                    "PUMA_RUNTIME_CACHE_PATH",
                    str(_BASE / "data" / "puma_runtime_cache.sqlite"),
                )
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            _CACHE = Cache(str(path))
    return _CACHE


def serper_cache_seconds() -> int:
    return max(0, int(os.getenv("PUMA_SERPER_CACHE_SECONDS", "259200")))


def page_cache_seconds() -> int:
    return max(0, int(os.getenv("PUMA_PAGE_CACHE_SECONDS", "300")))
