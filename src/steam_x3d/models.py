"""Immutable discovery and launch plans; constructing them has no side effects."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CacheGroup:
    """Logical CPUs sharing an L3 cache, its size in bytes, and socket ID."""

    cpus: frozenset[int]
    size: int
    package: int


@dataclass(frozen=True)
class Topology:
    """Host observations used to plan placement; empty groups mean undiscovered."""

    online: frozenset[int]
    allowed: frozenset[int]
    groups: tuple[CacheGroup, ...] = ()
    vendor: str = "unknown"
    diagnostic: str | None = None


@dataclass(frozen=True)
class PlacementPlan:
    """Requested CPU set and explanation, plus an optional Wine topology mapping."""

    cpus: frozenset[int]
    reason: str
    wine_topology: str | None = None

    @property
    def environment(self) -> dict[str, str]:
        """Return only the environment override represented by this plan."""
        return {"WINE_CPU_TOPOLOGY": self.wine_topology} if self.wine_topology else {}
