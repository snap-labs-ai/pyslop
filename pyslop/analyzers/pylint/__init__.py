from __future__ import annotations

import json
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

_DUPLICATE_CODE_LOC = re.compile(r"^==([^:\[]+):\[(\d+):(\d+)\]\s*$")


def _normalize_finding_path(path: str, repo_root: Path) -> str:
    if not path:
        return ""
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(repo_root)
        except ValueError:
            return candidate.as_posix()
    return candidate.as_posix()


def _modules_in_duplicate_code_message(message: str) -> tuple[str, ...]:
    modules: list[str] = []
    for line in message.splitlines():
        match = _DUPLICATE_CODE_LOC.match(line.strip())
        if match:
            modules.append(match.group(1))
    return tuple(modules)


def _existing_relative_paths_for_modules(
    modules: tuple[str, ...], repo_root: Path
) -> tuple[str, ...]:
    resolved: list[str] = []
    for module in modules:
        dotted = module.replace(".", "/")
        candidates = (f"{dotted}.py", f"{dotted}/__init__.py")
        for rel in candidates:
            path = Path(rel)
            if (repo_root / path).is_file():
                resolved.append(path.as_posix())
                break
    return tuple(resolved)


def _reattribute_duplicate_code_path(finding: Finding, repo_root: Path) -> Finding:
    if finding.rule_id not in ("duplicate-code", "R0801"):
        return finding
    message_paths = _existing_relative_paths_for_modules(
        _modules_in_duplicate_code_message(finding.message), repo_root
    )
    reported = _normalize_finding_path(finding.path, repo_root)
    if not message_paths or reported in message_paths:
        return finding
    return Finding(
        path=message_paths[0],
        line=finding.line,
        rule_id=finding.rule_id,
        message=finding.message,
    )


def _reattribute_duplicate_code_findings(
    findings: tuple[Finding, ...], repo_root: Path
) -> tuple[Finding, ...]:
    return tuple(_reattribute_duplicate_code_path(item, repo_root) for item in findings)


def parse_output(raw: str) -> list[Finding]:
    if not raw.strip():
        return []
    findings: list[Finding] = []
    for item in json.loads(raw):
        message = str(item.get("message") or "")
        if "fatal error while checking" in message:
            continue
        findings.append(
            Finding(
                path=str(item.get("path") or item.get("abspath") or ""),
                line=int(item.get("line") or 1),
                rule_id=str(item.get("symbol") or item.get("message-id") or "pylint"),
                message=message,
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
    command = tool_command("pylint", "--output-format=json")
    if config.config:
        command.append(f"--rcfile={config.config}")
    command.extend(targets)
    result = run_command(CommandSpec("pylint", command, parse_output, (32,)), executor)
    if result.errors or not result.findings:
        return result
    return AnalyzerRunResult(
        findings=_reattribute_duplicate_code_findings(result.findings, repo_root),
        errors=result.errors,
    )
