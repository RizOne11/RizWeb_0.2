from __future__ import annotations

import os
from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar

import httpx

from puma_scouts.models import Marketplace, Offer, ProductMission, ScanReport


_REPAIR_DISCOVERY = ContextVar("puma_repair_discovery", default=False)


@contextmanager
def repair_discovery_scope(enabled: bool = True):
    """Temporarily allow full discovery inside one async task only.

    ContextVar is used instead of mutating PUMA_REFRESH_ONLY so concurrent
    products cannot accidentally switch each other out of refresh mode.
    """
    token = _REPAIR_DISCOVERY.set(bool(enabled))
    try:
        yield
    finally:
        _REPAIR_DISCOVERY.reset(token)


class MarketplaceScout(ABC):
    marketplace: Marketplace

    async def http_client(self) -> httpx.AsyncClient:
        """Reuse one connection pool for the lifetime of this scout/job."""
        client = getattr(self, "_shared_http_client", None)
        if client is None or client.is_closed:
            timeout = float(getattr(self, "timeout", 15.0))
            self._shared_http_client = httpx.AsyncClient(
                timeout=timeout,
                limits=httpx.Limits(max_connections=80, max_keepalive_connections=40),
            )
        return self._shared_http_client

    async def aclose(self) -> None:
        client = getattr(self, "_shared_http_client", None)
        if client is not None and not client.is_closed:
            await client.aclose()
        self._shared_http_client = None

    def repair_mode(self) -> bool:
        return bool(_REPAIR_DISCOVERY.get())

    def refresh_only(self) -> bool:
        if self.repair_mode():
            return False
        flag = os.getenv("PUMA_REFRESH_ONLY", "0").strip().casefold()
        return flag in {"1", "true", "yes", "on"}

    def repair_query_limit(self) -> int:
        raw = os.getenv("PUMA_REPAIR_QUERY_LIMIT", "1")
        try:
            return max(1, min(int(raw), 2))
        except ValueError:
            return 1

    def bound_queries(self, queries):
        values = list(queries)
        return values[: self.repair_query_limit()] if self.repair_mode() else values

    def identity_refresh_limit(self) -> int:
        if self.marketplace == Marketplace.WEB_SHOPS:
            raw = os.getenv("PUMA_REFRESH_WEB_URL_LIMIT", "3")
        else:
            raw = os.getenv("PUMA_REFRESH_URL_LIMIT", "3")
        try:
            return max(1, min(int(raw), 12))
        except ValueError:
            return 3

    @abstractmethod
    async def generate_queries(self, mission: ProductMission) -> list[str]: ...

    @abstractmethod
    async def discover(self, mission: ProductMission, query: str) -> list[Offer]: ...

    @abstractmethod
    async def scan(self, mission: ProductMission) -> ScanReport: ...
