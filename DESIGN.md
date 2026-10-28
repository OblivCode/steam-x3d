# Architecture and design

The launcher requests CPU placement for one command. It separates observations
from policy so selection can be tested without changing real process affinity.

## Module boundaries

- `cli.py` validates options, gathers observations, coordinates the operation,
  and reports configured intent or sampled results.
- `models.py` contains immutable cache groups, topology observations, and plans.
- `topology.py` parses CPU lists and reads Linux online/cache/vendor data.
- `placement.py` chooses CPUs and plans the Wine environment without side effects.
- `launch.py` applies the plan to this process and replaces it with the command.
- `verify.py` samples the actual target thread masks without changing them.

The functional core receives topology and environment values; the imperative
shell reads sysfs/procfs, applies per-process affinity, and calls exec. No shared
launcher framework or runtime dependency is needed. Explicit launch CPU selection
bypasses cache/vendor discovery. Explicit verification bypasses discovery entirely.

## Terminology and selection

A **CCD** is a CPU chiplet containing cores that share an L3 cache. On supported
dual-CCD X3D processors, one CCD has additional V-Cache. A **CPU affinity mask**
is the set of logical CPUs a thread is allowed to run on; it does not reserve
those CPUs or prevent other applications from using them.

Automatic selection requires AMD vendor data and two non-overlapping, unequal
L3 sharing groups on a single socket. The larger group is selected and intersected
with online CPUs and the launcher's existing allowed mask. Physical SMT siblings
remain eligible because selection uses actual L3 sharing lists, never assumptions
about CPU numbering or dynamic preference rankings. Missing/ambiguous discovery
produces an explained pass-through launch.

## Linux and Wine requests

Linux affinity and Wine's topology request serve different launch paths. Ordinary
child processes inherit affinity, while Steam's runtime can start the game from
another process tree. Wine's mapping provides an additional request for Proton
games, but actual game-thread masks still need checking. Replacing the wrapper
with the command preserves exit statuses and signals without a resident supervisor,
a shell evaluation boundary, or changes to system scheduling.

Wine's [fill_cpu_override parser](https://github.com/ValveSoftware/wine/blob/bleeding-edge/dlls/ntdll/unix/system.c)
checks explicit host IDs against `sysconf(_SC_NPROCESSORS_ONLN)`, clamped to
`MAXIMUM_PROCESSORS`. That count is not the highest online Linux CPU ID plus one.
The [build-dependent processor limit](https://github.com/ValveSoftware/wine/blob/bleeding-edge/include/winnt.h)
is 32 or 64. We conservatively require IDs below `min(online_count, 32)` and a
matching logical count, accommodating either build. This knowingly declines
otherwise valid 64-bit-only mappings: the launcher cannot infer the eventual
Wine architecture, including prelaunchers and older WoW64 configurations.

An unrepresentable automatic mapping skips both affinity and environment changes;
an explicit launch request errors. Renumbering would select different physical
CPUs and is never a fallback. Existing conflicting `WINE_CPU_TOPOLOGY` remains
untouched by automatic mode; an explicit conflict fails. No
`PROTON_CPU_TOPOLOGY` behavior is assumed. Wine's guest SMT presentation remains
build-dependent even when Linux SMT siblings are eligible.

## Verification contract

Default verification expects the full detected V-Cache sharing group, ignoring
the checker's affinity and inherited Wine configuration. Explicit `--cpus` checks
a supplied intended set. These expectations cannot reconstruct the original launch
or prove that a wrapper caused the observed masks.

Every sampled thread must have a mask within the expected set. Task lists before
and after sampling detect observed churn; added, vanished, or absent threads make
the sample incomplete. This is a sequential observation, not an atomic snapshot:
short-lived threads may escape both listings and masks may change afterward.
The result makes no claim about descendants or future threads. Native exec tests
prove local inheritance, arguments, statuses and signals only. Steam/Proton game
placement and performance require in-game validation.
