"""AST check for too many public module-level functions."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from pyslop.analyzers.base import python_source_files
from pyslop.types import AnalyzerConfig, AnalyzerRunResult, Finding

ANALYZER_NAME = "too-many-module-functions"
RULE_ID = "too-many-module-functions"
DEFAULT_MAX_MODULE_FUNCTIONS = 10


def run(
    files: list[str],
    repo_root: Path,
    config: AnalyzerConfig,
    executor: object | None = None,
) -> AnalyzerRunResult:
    _ = executor
    limit = _max_module_functions(config)
    findings: list[Finding] = []
    for relative in python_source_files(files):
        findings.extend(_audit_file(repo_root / relative, relative, limit))
    return AnalyzerRunResult(findings=tuple(findings))


def _audit_file(path: Path, relative: str, limit: int) -> list[Finding]:
    tree = _parse_module(path)
    if tree is None:
        return []
    functions = _public_module_functions(tree)
    if len(functions) <= limit:
        return []
    overflow = functions[limit]
    return [
        Finding(
            path=relative,
            line=overflow.lineno,
            rule_id=RULE_ID,
            message=(
                f"Too many public module-level functions "
                f"({len(functions)} > {limit})"
            ),
        )
    ]


def _public_module_functions(
    tree: ast.Module,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    public: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for stmt in tree.body:
        if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if stmt.name.startswith("_"):
            continue
        public.append(stmt)
    return public


def _parse_module(path: Path) -> ast.Module | None:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return None
    if not isinstance(tree, ast.Module):
        return None
    return tree


def _max_module_functions(config: AnalyzerConfig) -> int:
    data = _analyzer_toml(config)
    value = data.get("max-module-functions", DEFAULT_MAX_MODULE_FUNCTIONS)
    if isinstance(value, int) and value > 0:
        return value
    return DEFAULT_MAX_MODULE_FUNCTIONS


def _analyzer_toml(config: AnalyzerConfig) -> dict[str, object]:
    path = Path(config.config) if config.config else None
    if path is None or not path.is_file():
        return {}
    try:
        parsed = tomllib.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
