from __future__ import annotations
from abc import ABC,abstractmethod
from puma_scouts.models import Marketplace,Offer,ProductMission,ScanReport
class MarketplaceScout(ABC):
    marketplace:Marketplace
    @abstractmethod
    async def generate_queries(self,mission:ProductMission)->list[str]:...
    @abstractmethod
    async def discover(self,mission:ProductMission,query:str)->list[Offer]:...
    @abstractmethod
    async def scan(self,mission:ProductMission)->ScanReport:...
