# Development

Keep implementation in `src/` with focused functions and small data types.
Split modules when that improves clarity; neither a single file nor a framework
is required. Avoid shared dependencies between the two launcher projects.
Runtime dependencies stay in Python's standard library.

Use the global developer writing profile: concise explanatory comments, function
docstrings where contracts need explanation, and Conventional Commits. Related
READMEs should use parallel introductions, terminology, and section order.
Explain architecture, terminology, design choices, and consequences in DESIGN.md;
link it from the README, which focuses on installation and usage.

Use uv. Run Ruff check/format, pytest, and `uv build` for changes.
Tests must not change the real display or global CPU settings. Game affinity
requests and actual verified thread masks are different claims. Document behavior
and limitations clearly; preserve command arguments without shell evaluation.

Do not publish, choose a project license, or change live Steam options as part of
routine development. User-authorized installation uses `uv tool install`.
