from __future__ import annotations

import errno
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess

from pyslop.types import AnalyzerRunResult, Finding

Executor = Callable[[Sequence[str]], CompletedProcess[str]]
DEFAULT_FAILURE_CODES = (2,)
PYTHON_SOURCE_SUFFIXES = (".py", ".pyi")


def parsed_tool_json_stdout(raw: str) -> object:
    if not raw.strip():
        return []
    return json.loads(raw)


def parsed_tool_json_list(raw: str) -> list[object]:
    data = parsed_tool_json_stdout(raw)
    if not isinstance(data, list):
        return []
    return data


@dataclass(frozen=True)
class CommandSpec:
    name: str
    command: Sequence[str]
    parse_output: Callable[[str], list[Finding]]
    failure_codes: tuple[int, ...] = DEFAULT_FAILURE_CODES


def run_command(
    spec: CommandSpec,
    executor: Executor | None = None,
) -> AnalyzerRunResult:
    result, errors = _invoke(spec, executor or _subprocess_run)
    if errors or result is None:
        skipped = () if errors else ((spec.name, "executable not on PATH"),)
        return AnalyzerRunResult(errors=errors, skipped=skipped)
    if result.returncode in spec.failure_codes:
        return AnalyzerRunResult(errors=(_exit_failure(spec.name, result),))
    findings, parsed_errors = _parsed_findings(spec, result.stdout)
    return AnalyzerRunResult(findings=findings, errors=parsed_errors)


def _invoke(
    spec: CommandSpec, runner: Executor
) -> tuple[CompletedProcess[str] | None, tuple[str, ...]]:
    try:
        return runner(spec.command), ()
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError) as exc:
        return _invoke_failure(spec.name, exc)


def _invoke_failure(
    name: str,
    exc: subprocess.TimeoutExpired | subprocess.CalledProcessError | OSError,
) -> tuple[None, tuple[str, ...]]:
    message = _failure_text(name, exc)
    if message is None:
        return None, ()
    return None, (message,)


def _failure_text(
    name: str,
    exc: subprocess.TimeoutExpired | subprocess.CalledProcessError | OSError,
) -> str | None:
    if isinstance(exc, subprocess.TimeoutExpired):
        timeout = f"{exc.timeout}s" if exc.timeout is not None else "unknown timeout"
        return f"{name} timed out after {timeout}"
    if isinstance(exc, subprocess.CalledProcessError):
        return _called_process_failure(name, exc)
    return None if _cannot_start(exc) else _started_failure_message(name, exc)


def _called_process_failure(name: str, exc: subprocess.CalledProcessError) -> str:
    detail = (exc.stderr or exc.stdout or str(exc)).strip()
    suffix = f": {detail}" if detail else ""
    return f"{name} failed with exit code {exc.returncode}{suffix}"


def _exit_failure(name: str, result: CompletedProcess[str]) -> str:
    detail = (result.stderr or result.stdout).strip()
    suffix = f": {detail}" if detail else ""
    return f"{name} failed with exit code {result.returncode}{suffix}"


def _parsed_findings(
    spec: CommandSpec, stdout: str
) -> tuple[tuple[Finding, ...], tuple[str, ...]]:
    try:
        return tuple(spec.parse_output(stdout)), ()
    except (ValueError, TypeError, UnicodeError) as exc:
        return (), (f"{spec.name} produced unparseable output: {exc}",)


def _cannot_start(exc: OSError) -> bool:
    if isinstance(exc, FileNotFoundError):
        return True
    return exc.errno == errno.ENOENT or getattr(exc, "winerror", None) == errno.ENOENT


def _started_failure_message(name: str, exc: BaseException) -> str:
    text = str(exc)
    if "WinError" in text or "Errno 2" in text:
        return f"{name} failed after start"
    return f"{name} failed to execute: {exc}"


def _subprocess_run(command: Sequence[str]) -> CompletedProcess[str]:
    return subprocess.run(
        command, capture_output=True, check=False, text=True, timeout=300
    )


def paths_for_command(repo_root: Path, files: list[str]) -> list[str]:
    return [str(repo_root / path) if repo_root != Path(".") else path for path in files]


def python_source_files(files: list[str]) -> list[str]:
    return [path for path in files if Path(path).suffix in PYTHON_SOURCE_SUFFIXES]


def tool_command(
    executable_name: str, *args: str, module_name: str | None = None
) -> list[str]:
    resolved = shutil.which(executable_name)
    if resolved:
        return [resolved, *args]
    return [sys.executable, "-m", module_name or executable_name, *args]
