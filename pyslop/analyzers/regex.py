from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from pyslop.types import (
    DETECT_KIND_REGEX,
    AnalyzerConfig,
    AnalyzerRunResult,
    Finding,
    RuleMetadata,
)


def run(
    files: list[str],
    repo_root: Path,
    _config: AnalyzerConfig,
    rules: dict[str, RuleMetadata] | None = None,
    executor: object | None = None,
) -> AnalyzerRunResult:
    _ = executor
    active = tuple(
        rule
        for rule in (rules or {}).values()
        if rule.detect_kind == DETECT_KIND_REGEX and rule.pattern
    )
    findings: list[Finding] = []
    for file_path in files:
        resolved = _resolve_repo_file(repo_root, file_path)
        if resolved is None:
            continue
        text = _read_utf8(resolved)
        if text is None:
            continue
        findings.extend(_scan_file(file_path, text, active))
    return AnalyzerRunResult(findings=tuple(findings))


def _resolve_repo_file(repo_root: Path, file_path: str) -> Path | None:
    try:
        resolved_root = repo_root.resolve()
        resolved_path = (resolved_root / file_path).resolve()
    except OSError:
        return None
    if resolved_path == resolved_root or resolved_path.is_relative_to(resolved_root):
        return resolved_path
    return None


def _read_utf8(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _scan_file(
    file_path: str, text: str, rules: tuple[RuleMetadata, ...]
) -> list[Finding]:
    findings: list[Finding] = []
    posix = PurePosixPath(Path(file_path).as_posix())
    for rule in rules:
        if rule.ignore and _matches_any(posix, rule.ignore):
            continue
        if rule.include and not _matches_any(posix, rule.include):
            continue
        pattern = re.compile(rule.pattern or "", re.IGNORECASE)
        for line_number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                findings.append(
                    Finding(
                        file_path,
                        line_number,
                        rule.rule_id,
                        f"Regex rule {rule.rule_id}",
                    )
                )
    return findings


def _matches_any(path: PurePosixPath, patterns: tuple[str, ...]) -> bool:
    text = path.as_posix()
    for pattern in patterns:
        if path.match(pattern):
            return True
        if pattern.startswith("**/") and path.match(pattern.removeprefix("**/")):
            return True
        if pattern.endswith("/**"):
            prefix = pattern.removesuffix("/**").rstrip("/")
            if text == prefix or text.startswith(f"{prefix}/"):
                return True
    return False
