# About

`pyslop` is an AXI-first CLI that aggregates Python static analyzer findings onto stdout as TOON tables for AI agents. Missing optional tools are skipped; started tool failures exit 2.

# Installation

Until the package is on PyPI, install from git:

```bash
uv add "pyslop @ git+https://github.com/snap-labs-ai/pyslop.git"
uv add "pyslop[analyzers] @ git+https://github.com/snap-labs-ai/pyslop.git"
```

```bash
pip install "pyslop @ git+https://github.com/snap-labs-ai/pyslop.git"
pip install "pyslop[analyzers] @ git+https://github.com/snap-labs-ai/pyslop.git"
```

Then `pyslop --help`.

### Initialization

```bash
pyslop init cursor --overwrite
# or for Claude:
pyslop init claude --overwrite
```

Install the bundled sample extension (protocol v1):

```bash
pyslop extensions detect-shims
```

See [docs/extensions.md](docs/extensions.md).

# CLI

Default `pyslop` / `pyslop run` diffs against `main` plus uncommitted files. That requires a git work tree; otherwise stdout is AXI `error:` (use `--files` or `--all`).

```bash
pyslop run
pyslop run --base develop
pyslop run --uncommitted-only --path src/
pyslop run --all
pyslop run --files src/ --files lib/util.py
pyslop run --stage ci --files-from .changed_python_lint_files.txt
pyslop run --timings --files src/main.py
pyslop analyzers
```

## Options

`pyslop run`:

- `--base <ref>`: Git ref to diff against (default: `main`).
- `--uncommitted-only`: Only analyze uncommitted changes.
- `--path <path>`: Restrict git-diff mode to a specific path.
- `--files <path>`: Analyze an explicit file or directory (repeat the flag).
- `--files-from <path>`: Read additional paths from a file, one per line.
- `--all`: Analyze all supported files without git.
- `--stage ci`: Include CI-stage analyzers (this is the only accepted value).
- `--strict`: Exit 1 when any finding remains (for CI and pre-commit).
- `--full`: Expand finding messages to 1500 characters.
- `--fields <list>`: Comma-separated columns from `path,line,rule,fix,message`.
- `--timings`: Print wall time per selected analyzer on stderr.
- `--no-cache`: Force filename analyzers to rescan (cache is `.pyslop/cache/`).
- `--config <path>`: Custom config file path.
- `--no-exclude`: Bypass configured exclude patterns.

Index analyzers (`inputs = "index"`) are not cached. `pyslop init` gitignores `.pyslop/cache/`.

Portable pre-commit:

```yaml
- id: pyslop
  name: pyslop
  entry: pyslop run --strict --files
  language: system
  types: [python]
```

`pyslop init`:

- `--target {cursor,claude}`: Skill destination (positional).
- `--overwrite`: Overwrite existing scaffold files.
- `--extensions`: Also install named bundled extensions.

# Configuration

Packaged analyzer configs and regex rules apply until you overlay paths.

```toml
exclude = ["alembic/**", "tests/fixtures/**"]

[analyzers]
disable = []

# Optional overlays:
# [analyzers.ruff]
# config = ".pyslop/analyzers/ruff/config.toml"

select = []
ignore = ["ruff-PLR0913"]
```

`select` and `ignore` use fnmatch against pyslop rule ids (`ruff-*`, `slop-words.*`).

## Regex rules

```toml
[[rules]]
id = "custom.no-foo"
name = "No foo"
fix = "Remove foo."
detect = { kind = "regex", pattern = '(?i)(?<!\w)foo(?!\w)', ignore = ["**/*.md"] }
```

Packaged slop-word patterns ship as `slop-words.*`. Overlay `[rules."slop-words.todo"]` to change fix text without copying the corpus.

## Extensions

See [docs/extensions.md](docs/extensions.md). Sample:

```toml
[[analyzers.extensions]]
id = "detect-shims"
entry-point = "pyslop_extensions/detect_shims/analyzer.py:analyze"
rules = "pyslop_extensions/detect_shims/rules.toml"
stage = "always"
inputs = "filenames"
```

Index extensions set `inputs = "index"` and `index-roots`. They receive `PYSLOP_INDEX_ROOTS`.

# How to run

1. **Stdout**: `pyslop` or `pyslop run` prints AXI TOON.
2. **Gates**: pre-commit and CI pass `--strict`. The skill does not.
3. **Skill**: the agent runs `pyslop run` and works through stdout.

# Versioning

This package is **0.y.z** until 1.0.0. Before 1.0.0, CLI flags and AXI table shape MAY change in a minor version. From 1.0.0 onward, breaking changes go in a major version. Every released version is recorded in `CHANGELOG.md`.

# Development

`uv` is required: tests and the wheel-contents check call `uv` (for example `uv build --wheel`). Install [uv](https://docs.astral.sh/uv/), then from this package directory:

```bash
uv sync --group dev --extra analyzers
uv run pytest
```
