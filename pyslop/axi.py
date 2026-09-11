from __future__ import annotations

import shutil
import sys
from pathlib import Path

from pyslop.types import Finding, RuleMetadata

AXI_DESCRIPTION = "Unified Python static analysis for AI slop"
PREVIEW_MESSAGE_CHAR_LIMIT = 120
FULL_MESSAGE_CHAR_LIMIT = 1500
ALLOWED_FINDING_FIELDS = ("path", "line", "rule", "fix", "message")
DEFAULT_FINDING_FIELDS = ALLOWED_FINDING_FIELDS
HELP_FULL = "Run `pyslop run --full` for full messages"
HELP_ANALYZERS = "Run `pyslop analyzers` to see skipped tools"


def parse_finding_fields(raw: str | None) -> tuple[str, ...] | None:
    if raw is None:
        return None
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts:
        raise ValueError("unknown finding field: (empty)")
    allowed = set(ALLOWED_FINDING_FIELDS)
    unknown = [part for part in parts if part not in allowed]
    if unknown:
        raise ValueError(f"unknown finding field: {unknown[0]}")
    return tuple(parts)


def render_findings(
    findings: list[Finding] | tuple[Finding, ...],
    rules: dict[str, RuleMetadata],
    *,
    repo_root: Path | None = None,
    full: bool = False,
    bin_path: str | None = None,
    fields: tuple[str, ...] | None = None,
    skipped: tuple[tuple[str, str], ...] = (),
) -> str:
    if repo_root:
        findings = [_relativize(finding, repo_root) for finding in findings]
    columns = fields or DEFAULT_FINDING_FIELDS
    limit = FULL_MESSAGE_CHAR_LIMIT if full else PREVIEW_MESSAGE_CHAR_LIMIT
    lines = [
        f"bin: {bin_path or _bin_display()}",
        f"description: {AXI_DESCRIPTION}",
    ]
    truncated = False
    if not findings:
        lines.append("findings: 0 in this file set")
    else:
        count = len(findings)
        lines.append(f"count: {count} of {count}")
        header = ",".join(columns)
        lines.append(f"findings[{count}]{{{header}}}:")
        for finding in findings:
            cells, was_truncated = _finding_cells(finding, rules, columns, limit)
            truncated = truncated or was_truncated
            lines.append(f"  {','.join(cells)}")
    _append_skipped(lines, skipped)
    help_items: list[str] = []
    if truncated and not full and "message" in columns:
        help_items.append(HELP_FULL)
    if truncated and full:
        help_items.append("Message truncated; total size is noted in the message cell")
    if skipped:
        help_items.append(HELP_ANALYZERS)
    if help_items:
        lines.append(f"help[{len(help_items)}]:")
        for item in help_items:
            lines.append(f"  {item}")
    return "\n".join(lines) + "\n"


def render_analyzers(
    runnable: list[str],
    skipped: tuple[tuple[str, str], ...],
    *,
    bin_path: str | None = None,
) -> str:
    lines = [
        f"bin: {bin_path or _bin_display()}",
        f"description: {AXI_DESCRIPTION}",
        f"analyzers[{len(runnable)}]:",
    ]
    for name in runnable:
        lines.append(f"  {name}")
    _append_skipped(lines, skipped)
    if skipped:
        lines.append("help[1]:")
        lines.append(f"  {HELP_ANALYZERS}")
    return "\n".join(lines) + "\n"


def render_error(message: str, help_line: str) -> str:
    return f"error: {_sanitize_error_text(message)}\nhelp: {help_line}\n"


def _finding_cells(
    finding: Finding,
    rules: dict[str, RuleMetadata],
    columns: tuple[str, ...],
    limit: int,
) -> tuple[list[str], bool]:
    fix = ""
    metadata = rules.get(finding.rule_id)
    if metadata is not None:
        fix = metadata.fix
    message, truncated = _maybe_truncate(finding.message, limit)
    values = {
        "path": _toon_cell(finding.path),
        "line": str(finding.line),
        "rule": _toon_cell(finding.rule_id),
        "fix": _toon_cell(fix),
        "message": _toon_cell(message),
    }
    cells = [values[column] for column in columns]
    if "message" not in columns:
        truncated = False
    return cells, truncated


def _append_skipped(lines: list[str], skipped: tuple[tuple[str, str], ...]) -> None:
    if not skipped:
        return
    lines.append(f"skipped[{len(skipped)}]{{name,reason}}:")
    for name, reason in skipped:
        lines.append(f"  {_toon_cell(name)},{_toon_cell(reason)}")


def _maybe_truncate(message: str, limit: int) -> tuple[str, bool]:
    if len(message) <= limit:
        return message, False
    preview = message[:limit]
    return (
        f"{preview}... (truncated, {len(message)} chars total)",
        True,
    )


def _sanitize_error_text(message: str) -> str:
    if "WinError" in message or "Errno 2" in message:
        name = message.split(" ", 1)[0]
        return f"{name} failed after start"
    return message


def _relativize(finding: Finding, repo_root: Path) -> Finding:
    candidate = Path(finding.path)
    if candidate.is_absolute():
        try:
            finding = Finding(
                path=candidate.relative_to(repo_root).as_posix(),
                line=finding.line,
                rule_id=finding.rule_id,
                message=finding.message,
            )
        except ValueError:
            finding = Finding(
                path=candidate.as_posix(),
                line=finding.line,
                rule_id=finding.rule_id,
                message=finding.message,
            )
    return finding


def _toon_cell(value: str) -> str:
    if value == "":
        return '""'
    if any(char in value for char in ',:"\n') or value[0].isspace():
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _bin_display() -> str:
    resolved = shutil.which("pyslop")
    if resolved:
        return _home_tilde(Path(resolved).resolve())
    raw = Path(sys.argv[0])
    if raw.stem == "pyslop":
        return _home_tilde(raw.resolve())
    return "pyslop"


def _home_tilde(raw: Path) -> str:
    home = Path.home()
    try:
        return "~/" + raw.relative_to(home).as_posix()
    except ValueError:
        return raw.as_posix()
