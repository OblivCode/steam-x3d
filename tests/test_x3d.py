"""Check topology, placement, thread verification, and the executable boundary."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from steam_x3d.cli import gather_topology, main
from steam_x3d.models import CacheGroup, Topology
from steam_x3d.placement import expected_cpus, plan_placement, select
from steam_x3d.topology import cache_bytes, discover, parse_cpus
from steam_x3d.verify import check_threads


def policy(online, groups, allowed, vendor, override, environment):
    plan = plan_placement(
        Topology(frozenset(online), frozenset(allowed), tuple(groups), vendor),
        override,
        environment,
        len(online),
    )
    return (set(plan.cpus), plan.reason)


def group(cpus, size, package=0):
    # CacheGroup stores bytes; fixture inputs use MiB for readable CCD sizes.
    return CacheGroup(frozenset(cpus), size * 1024 * 1024, package)


@pytest.fixture
def groups():
    """Model two CCDs with SMT siblings and unequal L3 capacity."""
    return [group([0, 1, 4, 5], 96), group([2, 3, 6, 7], 32)]


def test_parsing_rejects_bad_ranges():
    assert parse_cpus("0-2,8,10-11") == {0, 1, 2, 8, 10, 11}
    for value in ["", "4-1", "-1", "1;echo", "1,,2"]:
        with pytest.raises(ValueError):
            parse_cpus(value)
    assert cache_bytes("98304K") == 96 * 1024 * 1024


def test_select_respects_online_and_allowed_and_smt(groups):
    (cpus, _) = select(groups, set(range(7)), {0, 1, 2, 4, 6}, "AuthenticAMD")
    assert cpus == {0, 1, 4}
    reversed_groups = [group([0, 1], 32), group([8, 9], 96)]
    assert select(reversed_groups, {0, 1, 8, 9}, {0, 1, 8, 9}, "AuthenticAMD")[0] == {8, 9}


def test_ambiguous_or_unavailable_passes_through(groups):
    for candidate_groups in [
        groups[:1],
        [group([0], 32), group([1], 32)],
        [group([0], 96), group([1], 32, 1)],
    ]:
        assert not select(candidate_groups, {0, 1}, {0, 1}, "AuthenticAMD")[0]
    assert not select(groups, {2, 3}, {2, 3}, "AuthenticAMD")[0]
    assert not select(groups, set(range(8)), set(range(8)), "GenuineIntel")[0]


def test_override_validation_and_existing_environment(groups):
    online = allowed = set(range(8))
    assert policy(online, groups, allowed, "AuthenticAMD", "2-3", {})[0] == {2, 3}
    with pytest.raises(ValueError):
        policy(online, groups, allowed, "AuthenticAMD", "9", {})
    assert not policy(
        online, groups, allowed, "AuthenticAMD", None, {"WINE_CPU_TOPOLOGY": "2:2,3"}
    )[0]
    with pytest.raises(ValueError):
        policy(online, groups, allowed, "AuthenticAMD", "0-1", {"WINE_CPU_TOPOLOGY": "2:2,3"})


def test_sysfs_groups_are_deduplicated(tmp_path):
    root = tmp_path
    (root / "online").write_text("0-3")
    for cpu in range(4):
        path = root / f"cpu{cpu}"
        (path / "topology").mkdir(parents=True)
        (path / "topology/physical_package_id").write_text("0")
        index = path / "cache/index7"
        index.mkdir(parents=True)
        for key, value in {
            "level": "3",
            "type": "Unified",
            "size": "98304K" if cpu < 2 else "32768K",
            "shared_cpu_list": "0-1" if cpu < 2 else "2-3",
        }.items():
            (index / key).write_text(value)
    (online, groups) = discover(root)
    assert online == {0, 1, 2, 3}
    assert len(groups) == 2
    assert select(groups, online, online, "AuthenticAMD")[0] == {0, 1}


def test_real_exec_affinity_environment_and_argv():
    candidates = set(os.sched_getaffinity(0)) & set(
        range(min(32, os.sysconf("SC_NPROCESSORS_ONLN")))
    )
    if not candidates:
        pytest.skip("no allowed CPUs representable by conservative Wine mapping")
    cpu = min(candidates)
    environment = os.environ.copy()
    environment.pop("WINE_CPU_TOPOLOGY", None)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    code = "import os,json,sys; print(json.dumps([sorted(os.sched_getaffinity(0)),os.environ['WINE_CPU_TOPOLOGY'],sys.argv[1:]])); sys.exit(19)"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "steam_x3d",
            "--cpus",
            str(cpu),
            sys.executable,
            "-c",
            code,
            'space $literal "quote"',
        ],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 19, result.stderr
    assert json.loads(result.stdout) == [[cpu], f"1:{cpu}", ['space $literal "quote"']]


def test_check_samples_actual_thread_masks():
    selected = set(os.sched_getaffinity(0))
    assert check_threads(os.getpid(), selected)["within_selection"]


def test_sparse_linux_ids_rejected_for_wine():
    topology = Topology(
        frozenset({0, 1, 8, 9}),
        frozenset({0, 1, 8, 9}),
        (group([8, 9], 96), group([0, 1], 32)),
        "AuthenticAMD",
    )
    plan = plan_placement(topology, None, {}, 4)
    assert not plan.cpus
    assert "online processor count 4" in plan.reason
    with pytest.raises(ValueError, match="cannot represent"):
        plan_placement(topology, "8-9", {}, 4)
    # Sparse IDs are valid when every selected host ID stays below Wine's bound.
    assert plan_placement(topology, "0-1", {}, 4).wine_topology == "2:0,1"


def test_conservative_wine_build_limit():
    topology = Topology(frozenset(range(64)), frozenset(range(64)))
    with pytest.raises(ValueError, match="Wine build limit 32"):
        plan_placement(topology, "32", {}, 64)


def test_matching_environment_is_preserved():
    topology = Topology(frozenset(range(8)), frozenset(range(8)))
    plan = plan_placement(topology, "0-1", {"WINE_CPU_TOPOLOGY": "2:0,1"}, 8)
    assert plan.environment == {"WINE_CPU_TOPOLOGY": "2:0,1"}


def test_check_target_ignores_checker_affinity():
    topology = Topology(
        frozenset({0, 2}),
        frozenset({2}),
        (group([0, 1, 4, 5], 96), group([2, 3, 6, 7], 32)),
        "AuthenticAMD",
    )
    assert expected_cpus(topology, None) == {0, 1, 4, 5}
    assert expected_cpus(topology, "8-9") == {8, 9}


def test_explicit_launch_does_not_read_cache_or_vendor():
    with (
        patch("steam_x3d.cli.read_online", return_value={0, 1}),
        patch("steam_x3d.cli.os.sched_getaffinity", return_value={0, 1}),
        patch("steam_x3d.cli.discover_groups", side_effect=AssertionError),
        patch("steam_x3d.cli.vendor_id", side_effect=AssertionError),
    ):
        assert gather_topology(True, False).online == {0, 1}


def test_explicit_check_needs_no_discovery():
    with (
        patch("steam_x3d.cli.read_online", side_effect=AssertionError),
        patch("steam_x3d.cli.os.sched_getaffinity", side_effect=AssertionError),
    ):
        assert expected_cpus(gather_topology(True, True), "9") == {9}


def test_unavailable_automatic_topology_has_diagnostic():
    with (
        patch("steam_x3d.cli.read_online", return_value={0}),
        patch("steam_x3d.cli.os.sched_getaffinity", return_value={0}),
        patch("steam_x3d.cli.discover_groups", side_effect=OSError("missing cache")),
    ):
        plan = plan_placement(gather_topology(False, False), None, {}, 1)
        assert not plan.cpus
        assert "missing cache" in plan.reason


def sample(listings, masks):
    """Model task lists before/after sampling and affinity reads between them."""
    with (
        patch(
            "steam_x3d.verify.Path.iterdir",
            side_effect=[[Path(str(tid)) for tid in listing] for listing in listings],
        ),
        patch("steam_x3d.verify.os.sched_getaffinity", side_effect=masks),
    ):
        return check_threads(123, {0, 1})


def test_subset_and_escape():
    assert sample([{1, 2}, {1, 2}], [{0}, {1}])["verified_sample"]
    result = sample([{1}, {1}], [{0, 2}])
    assert result["sample_complete"]
    assert not result["verified_sample"]


def test_thread_churn_is_incomplete():
    for listings, masks in [
        ([{1}, {1, 2}], [{0}]),
        ([{1, 2}, {1}], [{0}, ProcessLookupError()]),
        ([{1}, set()], [{0}]),
        ([set(), set()], []),
    ]:
        result = sample(listings, masks)
        assert not result["sample_complete"]
        assert not result["verified_sample"]


def test_invalid_combinations(capsys):
    for arguments in [
        [],
        ["--check", "0"],
        ["--check", "1", "true"],
        ["--check", "1", "--info"],
        ["--info", "true"],
        ["--info", "--dry-run"],
        ["--dry-run"],
        [""],
    ]:
        with pytest.raises(SystemExit) as raised:
            main(arguments)
        assert raised.value.code == 2


def test_dry_run_no_mutation_and_literal_arguments(capsys):
    topology = Topology(frozenset({0}), frozenset({0}))
    with (
        patch("steam_x3d.cli.gather_topology", return_value=topology),
        patch("steam_x3d.cli.os.sysconf", return_value=1),
        patch.dict(os.environ, {}, clear=True),
        patch("steam_x3d.cli.launch", side_effect=AssertionError),
    ):
        assert main(["--cpus", "0", "--dry-run", "--", "echo", "$literal", "--info"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["command"] == ["echo", "$literal", "--info"]
    assert not report["verified_game_affinity"]


def test_check_ignores_inherited_wine_override(capsys):
    with (
        patch.dict(os.environ, {"WINE_CPU_TOPOLOGY": "conflict"}),
        patch("steam_x3d.cli.check_threads", return_value={"verified_sample": True}) as sample,
    ):
        assert main(["--cpus", "123", "--check", "7"]) == 0
    sample.assert_called_once_with(7, frozenset({123}))


def test_exec_native_exit_signal_and_missing_command():
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    # An existing user policy makes automatic mode pass through unchanged.
    environment["WINE_CPU_TOPOLOGY"] = "user policy"
    for code, status in [
        ("import sys; sys.exit(23)", 23),
        ("import os,signal; os.kill(os.getpid(),signal.SIGTERM)", -15),
    ]:
        result = subprocess.run(
            [sys.executable, "-m", "steam_x3d", sys.executable, "-c", code],
            env=environment,
            capture_output=True,
        )
        assert result.returncode == status, result.stderr
    result = subprocess.run(
        [sys.executable, "-m", "steam_x3d", "/missing/command"],
        env=environment,
        capture_output=True,
    )
    assert result.returncode == 127
