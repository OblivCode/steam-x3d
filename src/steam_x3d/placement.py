"""Pure CPU selection and Wine environment planning."""

from collections.abc import Mapping

from .models import CacheGroup, PlacementPlan, Topology
from .topology import parse_cpus


def select(
    groups: list[CacheGroup], online: set[int], allowed: set[int], vendor: str
) -> tuple[set[int], str]:
    """Select the larger of two unambiguous AMD L3 groups within both masks."""
    if vendor != "AuthenticAMD":
        return set(), "automatic selection supports AMD CPUs only"
    if len(groups) != 2 or len({group.package for group in groups}) != 1:
        return set(), "expected two L3 sharing groups on a single socket; no restriction applied"
    first, second = groups
    if first.cpus & second.cpus or first.size == second.size:
        return set(), "L3 groups overlap or have equal sizes; no unambiguous V-Cache group"
    chosen = max(groups, key=lambda group: group.size)
    selected = set(chosen.cpus) & online & allowed
    if not selected:
        return set(), "larger L3 group has no online CPUs in the existing allowed mask"
    return (
        selected,
        "selected online, allowed CPUs sharing the larger L3 cache (SMT siblings retained)",
    )


def expected_cpus(topology: Topology, override: str | None) -> frozenset[int]:
    """Choose a check target independent of the checker's mask and environment.

    An explicit check target describes the original intended CPUs, even if the
    checker cannot use them or some are now offline. It does not reconstruct a launch.
    """
    if override is not None:
        return frozenset(parse_cpus(override))
    all_cpus = set().union(*(group.cpus for group in topology.groups))
    selected, reason = select(list(topology.groups), all_cpus, all_cpus, topology.vendor)
    if not selected:
        raise ValueError(
            f"cannot determine check target: {topology.diagnostic or reason}; use --cpus"
        )
    return frozenset(selected)


def plan_placement(
    topology: Topology,
    override: str | None,
    environment: Mapping[str, str],
    host_cpu_count: int,
) -> PlacementPlan:
    """Plan both requests, preserving conflicting inherited Wine configuration.

    Wine bounds host IDs by online processor *count*, not highest Linux CPU ID.
    Use a conservative 32-CPU bound for both 32-bit and 64-bit Wine parsers.
    """
    if override is not None:
        selected = parse_cpus(override)
        unavailable = selected - (topology.online & topology.allowed)
        if unavailable:
            raise ValueError(f"requested CPUs are offline or disallowed: {sorted(unavailable)}")
        reason = "explicit CPU selection"
    else:
        selected, reason = select(
            list(topology.groups), set(topology.online), set(topology.allowed), topology.vendor
        )
        if topology.diagnostic:
            reason = (
                f"automatic topology unavailable: {topology.diagnostic}; no restriction applied"
            )
    if not selected:
        return PlacementPlan(frozenset(), reason)
    mapping = f"{len(selected)}:" + ",".join(map(str, sorted(selected)))
    existing = environment.get("WINE_CPU_TOPOLOGY")
    if existing is not None and existing != mapping:
        if override is not None:
            raise ValueError(
                "--cpus conflicts with existing WINE_CPU_TOPOLOGY; remove one override"
            )
        return PlacementPlan(
            frozenset(), "existing WINE_CPU_TOPOLOGY preserved; automatic policy not applied"
        )
    limit = min(host_cpu_count, 32)
    # Wine parses host IDs against processor count, so sparse Linux IDs may not fit.
    if limit <= 0 or len(selected) > limit or max(selected) >= limit:
        reason = (
            f"Wine mapping cannot represent selected host CPU IDs {sorted(selected)}: "
            f"IDs must be below min(online processor count {host_cpu_count}, conservative "
            "Wine build limit 32)"
        )
        if override is not None:
            raise ValueError(reason)
        return PlacementPlan(frozenset(), reason + "; no restriction applied")
    return PlacementPlan(frozenset(selected), reason, mapping)
