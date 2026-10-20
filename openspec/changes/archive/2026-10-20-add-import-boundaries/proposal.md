# Proposal

## Why

AI-generated Python imports across features, into private modules, and back at its siblings. File-scoped checkers never see that graph. Import Linter does, but only after someone writes the contracts, which is the second style guide pyslop exists to avoid.

## What Changes

- Add a builtin `import-boundaries` analyzer that checks the package import graph and reports each illegal import as an AXI row (path, line, rule, fix).
- Generate opinionated contracts for Import Linter's five built-in types (forbidden, protected, layers, independence, acyclic siblings). A module name that is not in the tree is omitted, not listed as a missing layer.
- Turn universal contracts on for every discovered root package: acyclic siblings, production importing tests, entrypoint imports, and private-module protection. Turn feature independence, hexagonal layers, and SDK bans on when the conventional directory names exist.
- Build the whole-package graph on a normal `pyslop run`. Keep a row only when the import site is in the selected file set. `pyslop run --all` reports every current violation.
- When the host already has `[tool.importlinter]`, check those contracts as well and attach a pyslop fix hint.
- **BREAKING** for installs that use the `analyzers` extra: `--strict` fails when a selected file contains an illegal import, including under `--all`. `analyzers.disable` turns the analyzer off.

## Capabilities

### New Capabilities

- `import-boundaries`: Generate opinionated import contracts from the tree and report violations as agent-actionable findings.

### Modified Capabilities

- None. The project has no existing specs.

## Impact

- New optional dependency `import-linter` on the `analyzers` extra. The analyzer is skipped when `lint-imports` is not on PATH, same as the other optional analyzers.
- Analyzer registry, runner dispatch, packaged rule metadata, and tests. `pyslop analyzers` lists the builtin.
- Rule ids are `import-boundaries.*` and honor existing `select` and `ignore`. No new CLI flags.
- A host whose tree matches the conventions can go from a green `--strict` gate to a red one. Diff mode only flags import sites in the selected files.
