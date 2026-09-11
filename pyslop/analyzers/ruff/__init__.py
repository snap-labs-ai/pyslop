from __future__ import annotations

from pathlib import Path

from pyslop.analyzers.base import (
    CommandSpec,
    Executor,
    tool_command,
    parsed_tool_json_list,
    python_source_files,
    run_command,
)
from pyslop.types import AnalyzerConfig, AnalyzerRunResult, Finding


def parse_output(raw: str) -> list[Finding]:
    findings: list[Finding] = []
    for item in parsed_tool_json_list(raw):
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "ruff")
        location_raw = item.get("location")
        location = location_raw if isinstance(location_raw, dict) else {}
        findings.append(
            Finding(
                path=str(item.get("filename", "")),
                line=int(location.get("row") or 1),
                rule_id=f"ruff-{code}" if code != "ruff" else "ruff",
                message=str(item.get("message") or code),
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
    command = tool_command("ruff", "check", "--output-format", "json")
    if config.config:
        command.extend(["--config", config.config])
    command.extend(targets)
    return run_command(CommandSpec("ruff", command, parse_output), executor)
