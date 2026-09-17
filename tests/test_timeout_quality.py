import asyncio

from puma_scouts.models import Marketplace, ProductMission, ScanHealth, ScanReport
from puma_scouts.production import _scan_source


class SlowUsefulScout:
    marketplace = Marketplace.PROM

    async def scan(self, mission):
        await asyncio.sleep(0.03)
        return ScanReport(
            article=mission.article,
            marketplace=self.marketplace,
            health=ScanHealth.FOUND,
            queries_generated=2,
            pages_scanned=3,
            candidates_seen=4,
            candidates_collected=3,
        )


def test_soft_source_timeout_must_not_discard_completed_scout_report():
    mission = ProductMission(article="ROW-1", source_data={"name": "Useful product"})
    scout, report = asyncio.run(
        _scan_source(SlowUsefulScout(), mission, wall_timeout=0.01)
    )

    assert scout.marketplace == Marketplace.PROM
    assert report.health == ScanHealth.FOUND
    assert report.queries_generated == 2
    assert report.pages_scanned == 3


class HungScout:
    marketplace = Marketplace.HOTLINE

    async def scan(self, mission):
        await asyncio.sleep(1)
        return ScanReport(
            article=mission.article,
            marketplace=self.marketplace,
            health=ScanHealth.FOUND,
        )


def test_hard_source_timeout_still_bounds_a_hung_scout():
    mission = ProductMission(article="ROW-2", source_data={"name": "Hung product"})
    scout, report = asyncio.run(
        _scan_source(HungScout(), mission, wall_timeout=0.01, hard_timeout=0.03)
    )

    assert scout.marketplace == Marketplace.HOTLINE
    assert report.health == ScanHealth.ACCESS_LIMITED
    assert report.errors == ["hard_timeout_0.03s"]
