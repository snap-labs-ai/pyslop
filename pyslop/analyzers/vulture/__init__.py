from __future__ import annotations

import re
from pathlib import Path

from pyslop.analyzers.base import (
    CommandSpec,
    Executor,
    tool_command,
    python_source_files,
    run_command,
)
from pyslop.types import AnalyzerConfig, AnalyzerRunResult, Finding


VULTURE_PATTERN = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+): (?P<message>.+? \(\d+% confidence\))$"
)


def parse_output(raw: str) -> list[Finding]:
    findings: list[Finding] = []
    for line in raw.splitlines():
        match = VULTURE_PATTERN.match(line.strip())
        if match:
            findings.append(
                Finding(
                    match.group("path"),
                    int(match.group("line")),
                    "vulture",
                    match.group("message"),
                )
            )
    return findings


def run(
    files: list[str],
    repo_root: Path,
    config: AnalyzerConfig,
    executor: Executor | None = None,
) -> AnalyzerRunResult:
    targets = python_source_files(files)
    if not targets:
        return AnalyzerRunResult()
    command = tool_command("vulture", *targets)
    whitelist = _find_whitelist(config.config, repo_root)
    if whitelist:
        command.append(str(whitelist))
    if config.config:
        command.extend(["--config", config.config])
    return run_command(CommandSpec("vulture", command, parse_output), executor)


def _find_whitelist(config_path: str | None, repo_root: Path) -> Path | None:
    if config_path:
        candidate = Path(config_path).parent / "vulture_whitelist.py"
        if candidate.exists():
            return candidate
    fallback = repo_root / "vulture_whitelist.py"
    if fallback.exists():
        return fallback
    return None
