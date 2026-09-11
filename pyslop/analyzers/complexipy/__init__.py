from __future__ import annotations

import subprocess
import tempfile
import tomllib
from pathlib import Path

from pyslop.analyzers.base import (
    Executor,
    _subprocess_run,
    parsed_tool_json_list,
    python_source_files,
)
from pyslop.types import AnalyzerConfig, AnalyzerRunResult, Finding

TOOL_FAILURE_EXIT_CODE = 2


def parse_output(raw: str) -> list[Finding]:
    findings: list[Finding] = []
    for item_raw in parsed_tool_json_list(raw):
        if not isinstance(item_raw, dict):
            continue
        item = item_raw
        path = str(item.get("path") or item.get("file") or "")
        line = _int_value(item.get("line") or item.get("line_start"), default=1)
        name = str(item.get("function") or item.get("name") or "<unknown>")
        complexity = _int_value(item.get("complexity"), default=0)
        threshold = _int_value(
            item.get("threshold") or item.get("max_complexity"), default=15
        )
        if complexity > threshold:
            findings.append(
                Finding(
                    path,
                    line,
                    "complexipy",
                    f"`{name}` has cognitive complexity of {complexity} (threshold {threshold})",
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
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as output:
        output_path = Path(output.name)
    command = [
        "complexipy",
        "--output-format",
        "json",
        "--output",
        str(output_path),
        *targets,
    ]
    if config.config:
        command.extend(_config_args(config.config))
    runner = executor or _subprocess_run
    try:
        execution_result = _run_complexipy_command(runner, command)
        return _handle_complexipy_execution_result(execution_result, output_path)
    finally:
        output_path.unlink(missing_ok=True)


def _handle_complexipy_execution_result(
    execution_result: AnalyzerRunResult | subprocess.CompletedProcess[str],
    output_path: Path,
) -> AnalyzerRunResult:
    if isinstance(execution_result, AnalyzerRunResult):
        return execution_result

    if execution_result.returncode == TOOL_FAILURE_EXIT_CODE:
        detail = (execution_result.stderr or execution_result.stdout).strip()
        suffix = f": {detail}" if detail else ""
        return AnalyzerRunResult(
            errors=(
                f"complexipy failed with exit code {TOOL_FAILURE_EXIT_CODE}{suffix}",
            )
        )

    raw = (
        output_path.read_text(encoding="utf-8")
        if output_path.exists()
        else execution_result.stdout
    )
    return _parse_complexipy_findings(raw)


def _load_complexipy_tool_block(path: Path) -> dict[str, object] | None:
    block: dict[str, object] | None = None
    if path.exists():
        try:
            parsed = tomllib.loads(path.read_bytes().decode("utf-8"))
            tool = parsed.get("tool")
            if isinstance(tool, dict):
                candidate = tool.get("complexipy")
                if isinstance(candidate, dict):
                    block = candidate
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            block = None
    return block


def _complexipy_cli_args(complexipy: dict[str, object]) -> list[str]:
    args: list[str] = []
    max_allowed = complexipy.get("max-complexity-allowed")
    if isinstance(max_allowed, int):
        args.extend(["--max-complexity-allowed", str(max_allowed)])
    excludes = complexipy.get("exclude")
    if isinstance(excludes, list):
        for entry in excludes:
            if isinstance(entry, str):
                args.extend(["--exclude", entry])
    return args


def _config_args(config_path: str) -> list[str]:
    complexipy = _load_complexipy_tool_block(Path(config_path))
    if complexipy is None:
        return []
    return _complexipy_cli_args(complexipy)


def _int_value(value: object, *, default: int) -> int:
    parsed_value = default
    if isinstance(value, int):
        parsed_value = value
    elif isinstance(value, float):
        parsed_value = int(value)
    elif isinstance(value, str):
        parsed_value = _parse_string_int(value, default)
    return parsed_value


def _parse_string_int(value: str, default: int) -> int:
    stripped = value.strip()
    if not stripped:
        return default
    try:
        return int(stripped)
    except ValueError:
        return default


def _run_complexipy_command(
    runner: Executor, command: list[str]
) -> AnalyzerRunResult | subprocess.CompletedProcess[str]:
    execution_result: AnalyzerRunResult | subprocess.CompletedProcess[str]
    try:
        execution_result = runner(command)
    except subprocess.TimeoutExpired as exc:
        timeout = f"{exc.timeout}s" if exc.timeout is not None else "unknown timeout"
        execution_result = AnalyzerRunResult(
            errors=(f"complexipy timed out after {timeout}",)
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        suffix = f": {detail}" if detail else ""
        execution_result = AnalyzerRunResult(
            errors=(f"complexipy failed with exit code {exc.returncode}{suffix}",)
        )
    except Exception as exc:
        execution_result = AnalyzerRunResult(
            errors=(f"complexipy failed to execute: {exc}",)
        )
    return execution_result


def _parse_complexipy_findings(raw: str) -> AnalyzerRunResult:
    try:
        return AnalyzerRunResult(findings=tuple(parse_output(raw)))
    except Exception as exc:
        return AnalyzerRunResult(
            errors=(f"complexipy produced unparseable output: {exc}",)
        )
