# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Version numbers follow [SemVer](https://semver.org/): **0.y.z** until 1.0.0 (minors MAY break CLI/AXI); after 1.0.0, breaks require a major version.

## Unreleased

- Add `examples/` host-repo copies of the detect-shims extension, pre-commit hook, and CI workflow (install pyslop as a third-party dependency).
- Cache filename-analyzer hits when tools report absolute paths (Windows ruff JSON).
- Add this repository's `.pre-commit-config.yaml` to dogfood `uv run pyslop run --strict`.
- Accept leftover `pyslop run` path arguments so pre-commit can pass staged files.
- Exclude `tests/**` in this repo's `pyslop.toml` so fixture source is not gated as slop.
- Default `pyslop init` writes `.agents/skills`; `pyslop init claude` is the only agent-specific target.

## 0.1.0

- AXI-first CLI that aggregates Python static analysis findings on stdout.
- Packaged analyzers, regex rules, detect-shims sample, and `pyslop init` skill.
