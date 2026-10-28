"""Apply the plan only to this process, then replace it with the command."""

import os
from collections.abc import Mapping, Sequence
from typing import NoReturn

from .models import PlacementPlan


def launch(command: Sequence[str], plan: PlacementPlan, environment: Mapping[str, str]) -> NoReturn:
    """Apply per-process affinity and replace this process with the command.

    The command arguments are passed unchanged; planned environment values overlay
    inherited values. ``execvpe`` preserves command exit status and signal behavior
    without a resident supervisor.
    """
    child_environment = dict(environment)
    child_environment.update(plan.environment)
    if plan.cpus:
        os.sched_setaffinity(0, plan.cpus)
    os.execvpe(command[0], command, child_environment)
