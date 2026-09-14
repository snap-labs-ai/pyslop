# About

`pyslop` runs Python static analysis on a git diff (or the files you pass) and prints one table of findings. Each row has a path, rule, message, and a `fix` hint. Agents work that list until it is empty; `--strict` fails pre-commit and CI if anything is left.

Ruff, Mypy, and similar tools still do their jobs. Configuring them one by one does not. Each tool has its own config, output, and exit code, so you end up stitching reports yourself and hoping CI, pre-commit, and the agent all look at the same files. `pyslop` keeps those analyzers, overlays slop-specific rules and extensions (placeholder comments, pass-through shims, and the rest of the generated residue those tools ignore), and returns a single AXI table. You do not maintain a second style guide.

That is why it stops slop better than a manual stack. Style and type checkers were not written to flag agent leftovers. A per-tool setup also leaves gaps: different file sets, findings an agent cannot act on, and a green CI that never saw the residue. One command, one table, one `--strict` gate closes that loop.

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
pyslop init
# Claude Code (writes .claude/skills instead of .agents/skills):
pyslop init claude --overwrite
```

Install the bundled sample extension (protocol v1):

```bash
pyslop extensions detect-shims
```

See [docs/extensions.md](docs/extensions.md) and the host-repo copies in [examples/](examples/).

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
- `--files <path>`: Analyze an explicit file or directory (repeat the flag). Extra path arguments after `run` are the same (pre-commit uses this).
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

After installing pyslop in **your** project, copy [examples/.pre-commit-config.yaml](examples/.pre-commit-config.yaml) to that repo's root and [examples/ci.yaml](examples/ci.yaml) to `.github/workflows/ci.yaml`. Pre-commit stays a host-repo tool (`uvx pre-commit install`); it is not a pyslop dependency. Local hooks use `--strict` on staged files. The CI example has two jobs: `pyslop-all` (`--all --stage ci --strict`) and `pyslop-changed` (`--stage ci --strict --base` vs the PR base). Keep the job that matches your gate. This repository's own hook is the root [`.pre-commit-config.yaml`](.pre-commit-config.yaml); do not replace it with the example file.

`pyslop init`:

- `claude`: Write `.claude/skills` instead of `.agents/skills`.
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
uvx pre-commit install
uv run pytest
```

The root [`.pre-commit-config.yaml`](.pre-commit-config.yaml) runs the in-tree CLI on staged Python files (`uv run pyslop run --strict`). [`pyslop.toml`](pyslop.toml) excludes `tests/**` because those files mention slop on purpose. Host-repo install snippets live in [examples/](examples/).
