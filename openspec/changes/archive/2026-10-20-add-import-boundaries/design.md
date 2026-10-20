# Design

## Context

Builtins are registered in `pyslop/analyzers/registry.py` and dispatched from `pyslop/runner.py`. Optional checkers are skipped when their executable is missing. Filename analyzers are cached per file. Index analyzers (`inputs = "index"`) are not cached, and they are skipped unless a selected path sits under `index_roots` or the run is `--all`. Findings are then dropped unless their path is in the selected file set. Fix text comes from packaged `rules.toml` via the rule id.

Import Linter's `lint_imports()` prints a report and returns a boolean. `Contract.check(graph, verbose)` returns chains with module names and line numbers through Grimp's `get_import_details`. A forbidden contract whose source package contains the forbidden module is a no-op while `as_packages` is true, because the modules overlap.

See `proposal.md` for why this exists and `specs/import-boundaries/spec.md` for the required behavior.

## Goals / Non-Goals

**Goals:**

- One builtin, `import-boundaries`, that generates the five contract types and reports import sites on a default `pyslop run`.
- Reuse the index-analyzer skip, the selected-file filter, and packaged fix text.
- Check a host `[tool.importlinter]` configuration with the same finding shape.

**Non-Goals:**

- A custom contract type, a Django layer profile, or a profile flag in `pyslop.toml`.
- Parsing `lint-imports` stdout, or caching the graph in `.pyslop/cache/`.
- Namespace packages that have no `__init__.py`.
- Replacing pylint's cyclic-import check. That stays file-local. This check is between sibling packages.
- Editing the fix-code-slop skill. Its fix column and multi-file exception already cover a boundary row.

## Decisions

### Builtin index analyzer

Add `import-boundaries` to `BUILTIN_ANALYZERS` and `BUILTIN_SPECS` with `stage = always`, `inputs = index`, and `index_roots = (".",)`. `.` matches every selected path, so a run with files builds the graph and a run with no files skips. `--all` does not skip.

Availability follows the other extras: the registry treats the analyzer as present when `lint-imports` is on PATH. The run function imports `importlinter` and Grimp. It does not subprocess.

Alternative: an extension under `pyslop_extensions/`. Rejected. Boundaries are a default, and extensions are opt-in copies.

Alternative: `inputs = filenames`. Rejected. The filename cache would reuse a finding after an unselected module changed the other end of a chain.

`import-linter` is added to the `analyzers` extra. It brings Grimp.

### Library check, not the CLI

Build one graph with `settings.GRAPH_BUILDER.build`, `cache_dir=None`, and `exclude_type_checking_imports=True`. Register the five built-in classes the way `importlinter.application.use_cases._get_built_in_contract_types` does, plus any `contract_types` from the host. For each contract, copy the graph, call `check(copy, verbose=False)`, and read metadata. Do not call `lint_imports()`.

`include_external_packages` is true only when a generated contract names an external module or the host session asks for it.

Alternative: shell out to `lint-imports`. Rejected. No stable line-oriented output, and the banner is not an AXI row.

### Roots and sys.path

A root package is a directory with `__init__.py` at the repo root or directly under `src/`, ignoring hidden directories. `tests` and `testing` are extra roots when they are importable, so a forbidden contract can see them, and they are not source modules for that ban. Host `root_packages` are added too. Insert each package's parent at the front of `sys.path` for the build and restore it in a `finally`. No root produces an empty result, not an error.

If no selected path ends in `.py` or `.pyi`, return before building the graph.

### Generate contracts from the graph

Generate after the graph exists, and only name modules that are in it, so a missing internal module does not raise `ValueError`. Generated contracts set `unmatched_ignore_imports_alerting` to `none`, leave `ignore_imports` empty, and keep indirect imports illegal.

- **Acyclic siblings.** One contract per non-test root. `depth = 1`. `skip_descendants` covers `**.migrations`, `**.tests`, `**.testing`, and `**.contrib`.
- **Independence.** For a parent with two or more direct children named `features`, `apps`, `plugins`, `slices`, `components`, or `bounded_contexts`, one contract whose `modules` are those children. A kernel is left off the list.
- **Layers.** A container needs one of `domain` or `core` and one outer name (`api`, `cli`, `web`, `routes`, `presentation`, `interfaces`, `infrastructure`, `infra`, `adapters`, `db`, `persistence`). Skip a container that has both `apps.py` and `models.py`. Tiers are outer, then middle (`application`, `services`, `usecases`, `use_cases`, `commands`, `handlers`), then inner. Join names that exist with ` : ` so siblings in a tier may import each other. Omit an empty tier. `exhaustive = true`. `exhaustive_ignores` is `migrations`, `tests`, and `conftest`.
- **Forbidden.** Non-test roots must not import an existing `tests` or `testing` package, `pytest`, or `unittest`. Other modules must not import an existing `__main__`, `manage`, or `scripts` module. `cli` is an outer layer, not this ban. Use `as_packages = false` and list concrete modules, because `as_packages = true` would treat a parent and its entrypoint as overlapping and keep the contract. When the hexagonal check is active, existing `domain` and `core` modules must not import `fastapi`, `flask`, `django`, `starlette`, `sqlalchemy`, `boto3`, `requests`, `httpx`, `redis`, or `celery`.
- **Protected.** One contract per module named `internal`, `impl`, `_impl`, or starting with `_`. `allowed_importers` is the parent, so the parent's descendants may import it and cousins may not. `migrations` and `conftest` get an empty allow-list. When the hexagonal check is active, the SDK list is protected to the outer modules that exist.

A direct inner-tier import of an SDK is reported only as `import-boundaries.forbidden`. The same import is not also `import-boundaries.protected`. A middle-tier or other non-outer import of an SDK stays `import-boundaries.protected`. Indirect inner-tier dependence stays forbidden.

### Rows

Rule ids are `import-boundaries.acyclic-siblings`, `import-boundaries.independence`, `import-boundaries.layers`, `import-boundaries.forbidden`, and `import-boundaries.protected`. Host contracts use the matching id when their type is one of those five. The message is the chain (`a -> b (line) -> c (line)`), which is how an unselected edge stays visible. The finding path and line are an import site in the selected set, taken from `get_import_details`. The runner's existing filter is a second gate. Packaged fix text rejects a re-export, a pass-through, a lazy import, and a `TYPE_CHECKING` import.

Module paths come from the imported module's file, made repo-relative with POSIX separators.

### Host configuration

If `read_user_options` finds `pyproject.toml`, `setup.cfg`, or `.importlinter`, check those contracts on the same graph. `FileNotFoundError` means there is no host configuration. Invalid host options become an analyzer error, not a fake finding. Generated contracts still run.

### Tests

`tests/test_import_boundaries.py` builds tiny packages under `tmp_path` and calls the analyzer. Cover each contract type's pass and fail from the spec, the selected-file ratchet, `TYPE_CHECKING`, a Django-shaped skip, a missing package, and a host forbidden contract. Extend `tests/test_analyzers.py` for registration, the always stage, index inputs, and the PATH skip. No network and no `lint-imports` subprocess.

## Risks / Trade-offs

- [Graph build on every default run] → Return immediately when the selection has no Python. Pass `cache_dir=None` so Grimp cannot serve a stale graph. If `--timings` shows this dominating a large repo, a follow-up can move the stage to `ci`. That follow-up would change the spec's default-run requirement, so it is not part of this change.
- [Forbidden contract raises when a module is missing] → Emit only names present in the graph. External SDKs are named only together with `include_external_packages`.
- [`as_packages` overlap hides an entrypoint ban] → Concrete modules and `as_packages = false` for that ban.
- [Two rules want the same SDK import] → One row: forbidden for the inner tier, protected otherwise.
- [`--all --strict` goes red on a matching legacy tree] → Document `analyzers.disable = ["import-boundaries"]` as the rollback. Diff mode stays limited to selected import sites.
- [Host and generated contracts share a rule id] → `ignore` drops both. The message still names the contract.

## Migration Plan

Add `import-linter` to the `analyzers` extra and mention the disable list in the README next to the other builtins. Rollback is removing the extra or disabling the analyzer. No config migration and no cache format change.

## Open Questions

None. Layout contracts turn on from directory names, which is the behavior in the spec.
