"""Parse options, gather observations, coordinate policy, and report intent."""

import argparse
import json
import os
import sys

from .launch import launch
from .models import Topology
from .placement import expected_cpus, plan_placement
from .topology import discover_groups, read_online, vendor_id
from .verify import check_threads


def parser() -> argparse.ArgumentParser:
    """Build the command-line parser for inspection, checking, and launch modes."""
    result = argparse.ArgumentParser(
        description="Request V-Cache CCD placement for one game launch",
        epilog="Steam: steam-x3d %command%. With HDR: steam-hdr --gamescope steam-x3d %command%.",
    )
    result.add_argument(
        "--info", action="store_true", help="show detected topology without launching"
    )
    result.add_argument(
        "--dry-run",
        action="store_true",
        help="show requested CPU policy and command, without launching",
    )
    result.add_argument("--cpus", help="explicit online/allowed CPU list, e.g. 0-7,16-23")
    result.add_argument(
        "--check",
        type=int,
        metavar="PID",
        help="sample every thread's allowed CPU mask for this process; no changes",
    )
    result.add_argument("command", nargs=argparse.REMAINDER)
    return result


def gather_topology(explicit: bool, checking: bool) -> Topology:
    """Read only the host data needed by the requested mode.

    Optional automatic-discovery failures become diagnostics for pass-through
    launches; explicit selections and checks fail when required online data is absent.
    """
    # Explicit check targets require no machine discovery. Explicit launches need
    # online/allowed data only, so broken optional cache metadata cannot block them.
    if explicit and checking:
        return Topology(frozenset(), frozenset())
    allowed = frozenset() if checking else frozenset(os.sched_getaffinity(0))
    try:
        online = frozenset(read_online())
    except (OSError, ValueError) as exc:
        if explicit or checking:
            raise ValueError(f"online CPU data unavailable: {exc}") from exc
        return Topology(allowed, allowed, diagnostic=str(exc))
    if explicit:
        return Topology(online, allowed)
    try:
        groups = tuple(discover_groups(set(online)))
        vendor = vendor_id()
        return Topology(online, allowed, groups, vendor)
    except (OSError, ValueError) as exc:
        return Topology(online, allowed, diagnostic=str(exc))


def main(argv=None) -> int:
    """Validate options, report configured intent, sample masks, or exec a command."""
    if not sys.platform.startswith("linux"):
        print("steam-x3d: requires Linux CPU affinity and sysfs", file=sys.stderr)
        return 1
    options = parser()
    args = options.parse_args(argv)
    if args.command[:1] == ["--"]:
        args.command.pop(0)
    if args.check is not None and (args.command or args.info or args.dry_run):
        options.error("--check cannot be combined with commands, --info or --dry-run")
    if args.check is not None and args.check <= 0:
        options.error("PID must be positive")
    if args.info and (args.command or args.dry_run):
        options.error("--info cannot be combined with a command or --dry-run")
    if not args.command and not args.info and args.check is None:
        options.error("missing command")
    if args.command and not args.command[0]:
        options.error("command must not be empty")
    try:
        topology = gather_topology(args.cpus is not None, args.check is not None)
        if args.check is not None:
            expected = expected_cpus(topology, args.cpus)
            result = check_threads(args.check, expected)
            print(json.dumps(result, indent=2))
            return 0 if result["verified_sample"] else 1
        plan = plan_placement(topology, args.cpus, os.environ, os.sysconf("SC_NPROCESSORS_ONLN"))
        if args.info or args.dry_run:
            # This report describes the plan; it does not observe game-thread affinity.
            report = {
                "vendor": topology.vendor,
                "online_cpus": sorted(topology.online),
                "allowed_cpus": sorted(topology.allowed),
                "l3_groups": [
                    {"cpus": sorted(group.cpus), "bytes": group.size, "socket": group.package}
                    for group in topology.groups
                ],
                "selected_cpus": sorted(plan.cpus),
                "reason": plan.reason,
                "verified_game_affinity": False,
                "environment": plan.environment,
            }
            if args.dry_run:
                report["command"] = args.command
            print(json.dumps(report, indent=2))
            return 0
        print(f"steam-x3d: {plan.reason}", file=sys.stderr)
        try:
            launch(args.command, plan, os.environ)
        except FileNotFoundError as exc:
            print(f"steam-x3d: command not found: {exc.filename}", file=sys.stderr)
            return 127
        except PermissionError as exc:
            print(f"steam-x3d: command or affinity permission denied: {exc}", file=sys.stderr)
            return 126
    except (OSError, ValueError) as exc:
        print(f"steam-x3d: {exc}", file=sys.stderr)
        return 1
    return 0
