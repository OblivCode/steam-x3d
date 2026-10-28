"""Sample actual thread masks without changing the target process."""

import os
from pathlib import Path


def check_threads(pid: int, selected: set[int] | frozenset[int]) -> dict:
    """Check subset membership; observed thread churn makes the sample incomplete.

    Two task listings detect observed churn, not threads that appear and disappear
    between listings. This is a sequential sample, never an atomic process snapshot.
    """
    if pid <= 0:
        raise ValueError("PID must be positive")
    if not selected:
        raise ValueError("cannot check placement without an expected CPU group")
    task_directory = Path(f"/proc/{pid}/task")
    before = {int(task.name) for task in task_directory.iterdir()}
    threads = {}
    vanished = set()
    for tid in sorted(before):
        try:
            threads[str(tid)] = sorted(os.sched_getaffinity(tid))
        except ProcessLookupError:
            vanished.add(tid)
    try:
        after = {int(task.name) for task in task_directory.iterdir()}
    except FileNotFoundError:
        after = set()
    vanished |= before - after
    added = after - before
    complete = bool(threads) and before == after and not vanished
    within = bool(threads) and all(set(mask) <= selected for mask in threads.values())
    return {
        "pid": pid,
        "expected_cpus": sorted(selected),
        "thread_masks": threads,
        "vanished_threads": sorted(vanished),
        "new_threads": sorted(added),
        "sample_complete": complete,
        "within_selection": within,
        "verified_sample": complete and within,
        "note": "sequential sample of this PID only; not descendants, future threads or launch reconstruction",
    }
