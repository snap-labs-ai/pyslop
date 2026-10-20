# Tasks

## 1. Register the analyzer

- [x] 1.1 Add `import-linter` to the `analyzers` extra in `pyproject.toml` and verify `uv sync --extra analyzers` puts `lint-imports` on PATH
- [x] 1.2 Register `import-boundaries` as an always-stage index builtin with `index_roots` of `.` and executable `lint-imports`, dispatch it from `pyslop/runner.py`, and verify `tests/test_analyzers.py` covers enabled, disabled, missing executable, stage, and index inputs
- [x] 1.3 Add `pyslop/templates/defaults/analyzers/import_boundaries/rules.toml` with the five fix hints, register it in `PACKAGED_ANALYZER_FILES`, and verify `load_packaged_rules` returns `import-boundaries.acyclic-siblings`, `import-boundaries.independence`, `import-boundaries.layers`, `import-boundaries.forbidden`, and `import-boundaries.protected`
- [x] 1.4 Document the extra and `analyzers.disable = ["import-boundaries"]` in `README.md` and verify those sentences name the analyzer

## 2. Build the graph

- [x] 2.1 Discover importable packages that have `__init__.py` at the repo root and directly under `src/`, treat `tests` and `testing` as extra roots, ignore hidden directories, and verify a `tmp_path` tree resolves those module names
- [x] 2.2 Build one graph with `settings.GRAPH_BUILDER.build` (`cache_dir=None`, `exclude_type_checking_imports=True`), restore `sys.path` after the build, return no findings when there is no package or no selected `.py`/`.pyi`, and verify those cases plus a `TYPE_CHECKING`-only import in `tests/test_import_boundaries.py`

## 3. Acyclic siblings and independence

- [x] 3.1 Generate acyclic-siblings contracts at depth 1, skipping children of `migrations`, `tests`, `testing`, and `contrib`, and verify a child cycle, a grandchild cycle, a deeper-only cycle, and a migrations cycle
- [x] 3.2 Generate an independence contract only for two or more children under `features`, `apps`, `plugins`, `slices`, `components`, or `bounded_contexts`, and verify a cross-feature import, a shared kernel, a shared module that imports a feature, and siblings outside those names

## 4. Hexagonal layers

- [x] 4.1 Generate layer contracts with ` : ` inside a tier, omit empty tiers, set `exhaustive` with ignores `migrations`, `tests`, and `conftest`, skip a package that has both `apps.py` and `models.py`, and verify inner-imports-outer, outer-wires-outer, inner-imports-middle, a missing middle tier, the Django skip, and a `helpers` sibling

## 5. Forbidden and protected

- [x] 5.1 Generate forbidden contracts for existing test packages, `pytest`, and `unittest`; for `__main__`, `manage`, and `scripts` with `as_packages` false and concrete modules; and for inner-tier SDK imports when layers apply. Verify an application importing `pytest`, tests importing the application, a library importing `__main__`, `__main__` importing the library, `cli` remaining legal, and `domain` importing `sqlalchemy` directly and through a re-export
- [x] 5.2 Generate protected contracts for `internal`, `impl`, `_impl`, and `_*` packages (parent allow-list), for `migrations` and `conftest` (empty allow-list), and for SDKs limited to existing outer modules. Verify a cousin import, a parent import, an application importing a migration, a middle-tier `httpx` import, an outer-tier `httpx` import, and a single forbidden row when `domain` imports an SDK directly

## 6. Findings and host contracts

- [x] 6.1 Put each violation on the import's path and line with the chain in the message and the packaged fix, drop chains that never touch the selected files, and verify the selected-edge ratchet and an all-files run
- [x] 6.2 Check host contracts from `read_user_options` on the same graph, return an analyzer error for invalid host options, and verify a host ban on `package.legacy` adds a finding under `import-boundaries.`
- [x] 6.3 Verify a default `pyslop run` with no stage flag reports a boundary finding, and `ignore = ["import-boundaries.layers"]` drops only the layers row
