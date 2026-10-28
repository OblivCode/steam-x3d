# steam-x3d

A small Python launcher for V-Cache CPU placement on **Linux / AMD X3D**.
Automatic cache detection is the default; an explicit CPU list is an alternative.

## Requirements

- Python 3.10 or newer; uv for development and installation.
- Linux with CPU affinity and readable sysfs CPU topology.
- A single-socket AMD CPU with two unequal L3 cache groups for automatic selection.

No third-party Python runtime dependencies are required. Steam/Proton behaviour
still needs in-game validation; Flatpak Steam is not yet validated.

## Install / update

From this folder:

```sh
uv sync
uv run pytest
uv tool install --editable --force .
steam-x3d --info
```

`uv tool install` creates an isolated environment and puts the command in uv's
user executable directory (normally `~/.local/bin`). Ensure that directory is
on the PATH inherited by Steam; `uv tool update-shell` helps configure a shell,
but you may need to restart Steam or log in again. For an immediate workaround,
use the command's absolute path in Steam.

Editable deployment means source changes take effect without copying a script.
After changing dependencies or entry points, rerun the install command.
`--force` replaces an existing command with this name: back up an unmanaged
launcher first. Uninstall with `uv tool uninstall steam-x3d`. A non-editable
install (`uv tool install --force .`) does not depend on keeping this source tree.

## Usage

```text
steam-x3d %command%
steam-hdr --gamescope steam-x3d %command%
steam-hdr steam-x3d %command%
```

Put X3D **inside** the HDR wrapper so Gamescope itself is not restricted by the
native Linux affinity request.

```sh
steam-x3d --info
steam-x3d --dry-run /usr/bin/true
steam-x3d --cpus 0-7,16-23 --dry-run /usr/bin/true
steam-x3d --check GAME_PID
steam-x3d --cpus 0-7,16-23 --check GAME_PID
```

The CPU list above is an example, not a portable assumption. Options after the
command belong to that command; `--` explicitly ends wrapper options.

## Behaviour

Automatic detection supports a single-socket AMD CPU with two non-overlapping,
unequal L3 cache sharing groups. It selects the larger L3 group, intersects it
with online CPUs and the wrapper's existing allowed mask, and retains available
SMT siblings. It does not guess CCD IDs from CPU numbering or dynamic rankings.

Unsupported or ambiguous automatic detection launches normally with an
explanation. `--cpus` overrides detection but must specify online, already allowed
CPUs; invalid explicit requests fail. Existing conflicting `WINE_CPU_TOPOLOGY`
is preserved by skipping the automatic policy. A conflicting explicit `--cpus`
request fails instead of silently mixing mappings.

Wine's explicit host CPU mapping validates each ID against the online CPU
**count**, which can reject valid Linux CPU IDs after CPUs go offline. The wrapper
also uses a conservative limit of 32 for compatibility with both 32-bit and
64-bit Wine parsers. If a selected host ID is at least `min(online_count, 32)`,
automatic mode launches without either request and explains why; an explicit
launch request fails. Host CPU IDs are never renumbered. This conservative policy
also applies to native commands because the wrapper cannot reliably identify the
eventual game runtime. Runtime CPU hotplug after planning can still invalidate a
request.

Explicit launch selection requires only readable online CPU data and the current
allowed mask. Missing vendor/cache metadata does not block `--cpus`.

Before replacing itself with the supplied command, the wrapper requests Linux
CPU affinity and sets `WINE_CPU_TOPOLOGY=N:host_cpu_ids` for Wine/Proton. Native
games ignore this variable. Wine's Windows-visible logical CPU / SMT presentation
depends on the Wine build; retaining physical SMT siblings does not guarantee
that Wine exposes the same guest core topology. No `PROTON_CPU_TOPOLOGY` variable
is assumed. Other applications remain free to use either CCD.

## Verification and limitations

**Configured intent is not verified game affinity.** Steam's runtime broker can
break ordinary process-affinity inheritance, and compatibility-tool behavior
varies. `--info` and `--dry-run` only report requested policy.

Use `--check PID` on the actual game process, not Steam or a prelauncher.
By default the expected set is the full detected V-Cache L3 group, independently
of the checker's own allowed mask or inherited `WINE_CPU_TOPOLOGY`. To check a
specific original override, use `--cpus LIST --check PID`; this explicit check
needs no topology discovery and accepts CPUs unavailable to the checker. Neither
mode reconstructs how the game was launched.

The command reads each visible thread's allowed mask and succeeds only when all
sampled masks are subsets of the expected set and no thread churn was observed.
JSON reports `expected_cpus`, `thread_masks`, `sample_complete`,
`within_selection`, and `verified_sample`. New/vanished threads or an empty sample
make verification incomplete and return failure. The sample is sequential: even
matching task lists cannot exclude a thread appearing and disappearing between
them. It checks this PID during sampling, not descendants or future threads.
Repeat during gameplay / after launcher handoffs. An observed current CPU number
is not a restriction check.

This first version does not use a daemon or privileged cgroups. It cannot promise
an unbreakable affinity boundary or better performance. Compare repeated runs of
the same scene, with identical settings and warmed shader caches. Look at frame
times and low-percentile performance, not only average FPS. Remove the wrapper
from launch options to roll back its per-launch policy.

Native exec affinity is tested locally. Steam/Proton end-to-end affinity and
performance still need in-game validation. Flatpak Steam is not validated.

Architecture, terminology, and design decisions: [DESIGN.md](DESIGN.md).

## Development

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv build
```

Development uses Python 3.12, with package support starting at 3.10. Tests use
sysfs fixtures, policy and thread-churn fixtures, plus actual child-process
affinity/argument/exit-status/signal checks;
they do not change the parent process or system scheduling settings.

References: [kernel CPU/cache ABI](https://github.com/torvalds/linux/blob/master/Documentation/ABI/testing/sysfs-devices-system-cpu),
[Valve Wine topology parser](https://github.com/ValveSoftware/wine/blob/bleeding-edge/dlls/ntdll/unix/system.c),
[Steam runtime affinity discussion](https://github.com/ValveSoftware/steam-runtime/issues/304#issuecomment-736607065),
[uv tools](https://docs.astral.sh/uv/concepts/tools/).
