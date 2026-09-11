from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from subprocess import CompletedProcess

from pyslop.path_utils import resolve_repo_path
from pyslop.types import AnalyzerRunResult, ExtensionConfig, Finding


Executor = Callable[[Sequence[str]], CompletedProcess[str]]
TOOL_FAILURE_MIN_EXIT_CODE = 2


def run_one_extension(
    extension: ExtensionConfig,
    files: list[str],
    repo_root: Path,
    executor: Executor | None = None,
) -> AnalyzerRunResult:
    runner = executor or _subprocess_run
    return _run_extension(extension, files, repo_root, runner)


def _run_extension(
    extension: ExtensionConfig,
    files: list[str],
    repo_root: Path,
    executor: Executor,
) -> AnalyzerRunResult:
    if extension.command:
        return _run_command_extension(extension, files, executor)
    if extension.entry_point:
        return _run_entry_point_extension(extension, files, repo_root)
    return AnalyzerRunResult(
        errors=(f"extension {extension.id} has no command or entry point",)
    )


def _run_command_extension(
    extension: ExtensionConfig,
    files: list[str],
    executor: Executor,
) -> AnalyzerRunResult:
    findings: list[Finding] = []
    errors: list[str] = []
    command = [*extension.command, *files]
    result = executor(command)
    if result.returncode >= TOOL_FAILURE_MIN_EXIT_CODE:
        detail = (result.stderr or result.stdout).strip()
        suffix = f": {detail}" if detail else ""
        errors.append(
            f"extension {extension.id} failed with exit code {result.returncode}{suffix}"
        )
        return AnalyzerRunResult(findings=tuple(findings), errors=tuple(errors))
    try:
        findings.extend(_findings_from_json(result.stdout))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"extension {extension.id} returned invalid findings: {exc}")
    return AnalyzerRunResult(findings=tuple(findings), errors=tuple(errors))


def _run_entry_point_extension(
    extension: ExtensionConfig,
    files: list[str],
    repo_root: Path,
) -> AnalyzerRunResult:
    try:
        source, function_name = (
            extension.entry_point.rsplit(":", 1) if extension.entry_point else ("", "")
        )
        function = _load_entry_point_function(source, function_name, repo_root)
        findings = function(files, repo_root, extension.config)
        return AnalyzerRunResult(findings=tuple(findings))
    except Exception as exc:  # noqa: BLE001 - extension failures are isolated by design.
        return AnalyzerRunResult(errors=(f"extension {extension.id} failed: {exc}",))


def _load_entry_point_function(
    source: str, function_name: str, repo_root: Path
) -> Callable[[list[str], Path, str | None], list[Finding]]:
    if source.endswith(".py"):
        path = resolve_repo_path(repo_root, source)
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot import {source}")
        module = importlib.util.module_from_spec(spec)
        if spec.name is not None:
            sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return getattr(module, function_name)
    return getattr(importlib.import_module(source), function_name)


def _findings_from_json(raw: str) -> list[Finding]:
    data = json.loads(raw or "[]")
    if not isinstance(data, list):
        raise TypeError("stdout must be a JSON array")
    return [_finding_from_dict(item) for item in data]


def _finding_from_dict(value: object) -> Finding:
    if not isinstance(value, dict):
        raise TypeError("finding must be an object")
    return Finding(
        path=str(value["path"]),
        line=int(value["line"]),
        rule_id=str(value["rule_id"]),
        message=str(value["message"]),
    )


def _subprocess_run(command: Sequence[str]) -> CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, check=False, text=True)
