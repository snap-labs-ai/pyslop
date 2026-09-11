"""detect-secrets analyzer integration."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path
from typing import cast

from pyslop.analyzers.base import Executor, _subprocess_run, parsed_tool_json_stdout
from pyslop.types import AnalyzerConfig, AnalyzerRunResult, Finding

TOOL_ERROR_EXIT_CODE = 2


def parse_output(raw: str) -> list[Finding]:
    """Convert detect-secrets JSON stdout into normalized findings."""
    data = parsed_tool_json_stdout(raw)
    if not isinstance(data, dict):
        return []
    results = data.get("results")
    if not isinstance(results, dict):
        return []

    findings: list[Finding] = []
    for file_findings_raw in results.values():
        if isinstance(file_findings_raw, list):
            findings.extend(_parse_file_findings(file_findings_raw))
    return findings


def run(  # noqa
    files: list[str],
    _repo_root: Path,
    config: AnalyzerConfig,
    executor: Executor | None = None,
) -> AnalyzerRunResult:
    """Run detect-secrets-hook and normalize its JSON output."""
    runner = executor or _subprocess_run
    try:
        result = runner(
            ["detect-secrets-hook", "--json", *_config_args(config), *files]
        )
    except subprocess.TimeoutExpired as exc:
        timeout = f"{exc.timeout}s" if exc.timeout is not None else "unknown timeout"
        return AnalyzerRunResult(errors=(f"detect-secrets timed out after {timeout}",))
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        suffix = f": {detail}" if detail else ""
        return AnalyzerRunResult(
            errors=(f"detect-secrets failed with exit code {exc.returncode}{suffix}",)
        )
    except Exception as exc:
        return AnalyzerRunResult(errors=(f"detect-secrets failed to execute: {exc}",))
    if result.returncode >= TOOL_ERROR_EXIT_CODE:
        detail = (result.stderr or result.stdout).strip()
        suffix = f": {detail}" if detail else ""
        return AnalyzerRunResult(
            errors=(
                f"detect-secrets failed with exit code {result.returncode}{suffix}",
            )
        )
    try:
        return AnalyzerRunResult(findings=tuple(parse_output(result.stdout)))
    except Exception as exc:
        return AnalyzerRunResult(
            errors=(f"detect-secrets produced unparseable output: {exc}",)
        )


def _config_args(config: AnalyzerConfig) -> list[str]:
    if config.config is None:
        return []
    parsed = _load_config(Path(config.config))
    args: list[str] = []
    baseline = parsed.get("baseline")
    if isinstance(baseline, str) and baseline:
        args.extend(["--baseline", baseline])
    disable_plugins = parsed.get("disable_plugins")
    if isinstance(disable_plugins, list):
        for plugin in disable_plugins:
            if isinstance(plugin, str):
                args.extend(["--disable-plugin", plugin])
    return args


def _load_config(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        return cast(
            "dict[str, object]", tomllib.loads(path.read_bytes().decode("utf-8"))
        )
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}


def _parse_file_findings(file_findings_raw: list[object]) -> list[Finding]:
    findings: list[Finding] = []
    for finding_raw in file_findings_raw:
        if not isinstance(finding_raw, dict):
            continue
        finding = cast("dict[str, object]", finding_raw)
        path = str(finding.get("filename") or "")
        line = _int_value(finding.get("line_number"), default=1)
        type_value = str(finding.get("type") or "Secret")
        findings.append(Finding(path, line, "secrets", f"{type_value} detected"))
    return findings


def _int_value(value: object, *, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return default
