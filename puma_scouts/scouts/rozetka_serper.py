from __future__ import annotations

from puma_scouts.models import Marketplace
from puma_scouts.scouts.catalog import CatalogScout


class RozetkaSerperScout(CatalogScout):
    """Rozetka experiment: Serper-only discovery, then normal PUMA validation.

    Initial discovery deliberately skips Rozetka native search and generic external
    search. Serper returns candidate product URLs, while extraction, identity
    validation, Identity Map persistence, direct refresh and repair metrics reuse
    the current PUMA pipeline unchanged.
    """

    marketplace = Marketplace.ROZETKA
    host = "rozetka.com.ua"
    allow_subdomains = True
    product_path_hints = ("/p",)
    search_templates = ()

    async def _native_candidate_urls(self, client, query):
        return []

    async def _external_candidate_urls(self, client, query):
        return []
