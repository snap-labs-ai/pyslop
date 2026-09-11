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


MYPY_PATTERN = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+):(?:(?P<column>\d+):)? (?P<kind>error|note|warning): (?P<message>.+?)(?: \[(?P<code>[-a-z0-9_]+)\])?$"
)


def parse_output(raw: str) -> list[Finding]:
    findings: list[Finding] = []
    for line in raw.splitlines():
        match = MYPY_PATTERN.match(line.strip())
        if match:
            kind = match.group("kind")
            code = match.group("code")
            suffix = f"[{code}]" if code else ""
            findings.append(
                Finding(
                    path=match.group("path"),
                    line=int(match.group("line")),
                    rule_id=f"mypy-{kind}{suffix}",
                    message=f"{kind}: {match.group('message')}",
                )
            )
    return findings


def run(
    files: list[str],
    _repo_root: Path,
    config: AnalyzerConfig,
    executor: Executor | None = None,
) -> AnalyzerRunResult:
    targets = python_source_files(files)
    if not targets:
        return AnalyzerRunResult()
    return run_command(
        CommandSpec("mypy", _command_for_targets(targets, config), parse_output),
        executor,
    )


def _command_for_targets(targets: list[str], config: AnalyzerConfig) -> list[str]:
    command = tool_command("mypy", "--explicit-package-bases", "--namespace-packages")
    if config.config:
        command.append(f"--config-file={config.config}")
    command.extend(targets)
    return command
