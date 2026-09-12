"""Detect-shims analyzer implementation for the bundled extension."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from pyslop.types import Finding


def analyze(
    files: list[str], repo_root: Path, config_path: str | None
) -> list[Finding]:
    _ = config_path
    findings: list[Finding] = []
    for file_path in sorted(files):
        if not file_path.endswith(".py"):
            continue
        findings.extend(_audit_file(repo_root / file_path, file_path))
    return findings


def _get_arg_names(args: ast.arguments) -> list[str]:
    names: list[str] = [arg.arg for arg in args.posonlyargs]
    names.extend(arg.arg for arg in args.args if arg.arg not in ("self", "cls"))
    vararg = args.vararg
    if vararg is not None:
        names.append(vararg.arg)
    names.extend(arg.arg for arg in args.kwonlyargs)
    kwarg = args.kwarg
    if kwarg is not None:
        names.append(kwarg.arg)
    return names


def _get_call_arg_names(call: ast.Call) -> list[str] | None:
    names: list[str] = []
    for arg in call.args:
        if isinstance(arg, ast.Name):
            names.append(arg.id)
            continue
        if isinstance(arg, ast.Starred) and isinstance(arg.value, ast.Name):
            names.append(arg.value.id)
            continue
        return None
    if call.keywords:
        return None
    return names


def _is_super_call(call: ast.Call) -> bool:
    return (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Call)
        and isinstance(call.func.value.func, ast.Name)
        and call.func.value.func.id == "super"
    )


def _get_target_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return "<complex_call>"


def _parse_python_tree(filepath: Path) -> ast.AST | None:
    try:
        source = filepath.read_text(encoding="utf-8")
        return ast.parse(source, filename=str(filepath))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        print(
            f"detect_shims: skipped {filepath.as_posix()}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return None


def _strip_leading_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if (
        len(body) > 1
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _return_await_call(stmt: ast.stmt) -> ast.Call | None:
    if not isinstance(stmt, ast.Return) or stmt.value is None:
        return None
    ret_val = stmt.value
    expression = ret_val.value if isinstance(ret_val, ast.Await) else ret_val
    if not isinstance(expression, ast.Call):
        return None
    return expression


def _body_single_return_call(body: list[ast.stmt]) -> ast.Call | None:
    if len(body) != 1:
        return None
    return _return_await_call(body[0])


def _target_if_pure_shim(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    call: ast.Call,
) -> str | None:
    signature_arguments = _get_arg_names(node.args)
    call_arguments = _get_call_arg_names(call)
    if (
        _is_super_call(call)
        or call_arguments is None
        or signature_arguments != call_arguments
        or not signature_arguments
    ):
        return None
    target_name = _get_target_name(call)
    return target_name if target_name != node.name else None


def _maybe_pure_shim_finding(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    file_path: str,
) -> Finding | None:
    if not node.body:
        return None
    body = _strip_leading_docstring(node.body)
    call = _body_single_return_call(body)
    target = _target_if_pure_shim(node, call) if call is not None else None
    if target is None:
        return None
    return Finding(
        path=file_path,
        line=node.lineno,
        rule_id="pure-shim",
        message=(
            f"'{node.name}' appears to be a pure shim wrapping "
            f"'{target}'. Replace callers with direct calls to '{target}'."
        ),
    )


def _audit_file(filepath: Path, relative_file_path: str) -> list[Finding]:
    tree = _parse_python_tree(filepath)
    if tree is None:
        return []
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        finding = _maybe_pure_shim_finding(node, relative_file_path)
        if finding is not None:
            findings.append(finding)
    return findings
