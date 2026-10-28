"""Read Linux CPU availability and optional cache metadata."""

import re
from pathlib import Path

from .models import CacheGroup


def read_online(root: Path = Path("/sys/devices/system/cpu")) -> set[int]:
    """Read Linux's online CPU list from the supplied sysfs root."""
    return parse_cpus((root / "online").read_text())


def parse_cpus(text: str) -> set[int]:
    """Expand a Linux-style comma/range CPU list; reject malformed or huge ranges."""
    result = set()
    for item in text.strip().split(","):
        if not re.fullmatch(r"\d+(?:-\d+)?", item):
            raise ValueError(f"invalid CPU list: {text!r}")
        parts = [int(part) for part in item.split("-")]
        start, end = parts[0], parts[-1]
        if end < start or end > 1_000_000:
            raise ValueError(f"invalid CPU range: {item}")
        result.update(range(start, end + 1))
    return result


def cache_bytes(text: str) -> int:
    """Convert a sysfs cache size with optional K/M/G suffix to bytes (base 1024)."""
    match = re.fullmatch(r"(\d+)\s*([KMG]?)", text.strip(), re.IGNORECASE)
    if match is None:
        raise ValueError(f"invalid cache size: {text!r}")
    return int(match[1]) * (1024 ** ("", "K", "M", "G").index(match[2].upper()))


def discover(root: Path = Path("/sys/devices/system/cpu")) -> tuple[set[int], list[CacheGroup]]:
    """Read online CPUs and their distinct unified L3 sharing groups."""
    online = read_online(root)
    return online, discover_groups(online, root)


def discover_groups(
    online: set[int], root: Path = Path("/sys/devices/system/cpu")
) -> list[CacheGroup]:
    """Group online CPUs by socket and L3 shared list; inconsistent data raises."""
    groups = {}
    for cpu in sorted(online):
        directory = root / f"cpu{cpu}"
        package = int((directory / "topology/physical_package_id").read_text())
        for index in (directory / "cache").glob("index*"):
            if (index / "level").read_text().strip() != "3":
                continue
            if (index / "type").read_text().strip().lower() != "unified":
                continue
            cpus = frozenset(parse_cpus((index / "shared_cpu_list").read_text()))
            size = cache_bytes((index / "size").read_text())
            key = (package, cpus)
            group = CacheGroup(cpus, size, package)
            if key in groups and groups[key] != group:
                raise ValueError("inconsistent L3 cache data")
            groups[key] = group
    return sorted(groups.values(), key=lambda group: min(group.cpus))


def vendor_id(path: Path = Path("/proc/cpuinfo")) -> str:
    """Return the first Linux CPU vendor identifier, or ``unknown`` if absent."""
    for line in path.read_text().splitlines():
        if line.startswith("vendor_id"):
            return line.split(":", 1)[1].strip()
    return "unknown"
