from __future__ import annotations

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
    runner = executor or _subprocess_run
    findings: tuple[Finding, ...] = ()
    errors: tuple[str, ...] = ()
    result: CompletedProcess[str] | None = None
    try:
        result = runner(spec.command)
    except subprocess.TimeoutExpired as exc:
        timeout = f"{exc.timeout}s" if exc.timeout is not None else "unknown timeout"
        errors = (f"{spec.name} timed out after {timeout}",)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        suffix = f": {detail}" if detail else ""
        errors = (f"{spec.name} failed with exit code {exc.returncode}{suffix}",)
    except Exception as exc:
        if _cannot_start(exc):
            return AnalyzerRunResult(skipped=((spec.name, "executable not on PATH"),))
        errors = (_started_failure_message(spec.name, exc),)
    if not errors and result and result.returncode in spec.failure_codes:
        detail = (result.stderr or result.stdout).strip()
        suffix = f": {detail}" if detail else ""
        errors = (f"{spec.name} failed with exit code {result.returncode}{suffix}",)
    if not errors and result:
        try:
            findings = tuple(spec.parse_output(result.stdout))
        except Exception as exc:
            errors = (f"{spec.name} produced unparseable output: {exc}",)
    return AnalyzerRunResult(findings=findings, errors=errors)


def _cannot_start(exc: BaseException) -> bool:
    if isinstance(exc, FileNotFoundError):
        return True
    if isinstance(exc, OSError):
        if exc.errno == 2:
            return True
        if getattr(exc, "winerror", None) == 2:
            return True
    return False


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
