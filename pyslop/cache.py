from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from pyslop.types import INPUTS_FILENAMES, AnalyzerRunResult, AnalyzerSpec, Finding

CACHE_DIRNAME = "cache"


def cache_root(repo_root: Path) -> Path:
    return repo_root / ".pyslop" / CACHE_DIRNAME


def fingerprint(parts: tuple[bytes, ...]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part)
    return digest.hexdigest()


def load_cached_result(
    repo_root: Path,
    spec: AnalyzerSpec,
    files: list[str],
    config_bytes: bytes,
) -> AnalyzerRunResult | None:
    if getattr(spec, "inputs", INPUTS_FILENAMES) != INPUTS_FILENAMES:
        return None
    findings: list[Finding] = []
    for file_path in files:
        payload = _read_entry(repo_root, spec.name, file_path, config_bytes)
        if payload is None:
            return None
        findings.extend(payload)
    return AnalyzerRunResult(findings=tuple(findings))


def store_cached_result(
    repo_root: Path,
    spec: AnalyzerSpec,
    files: list[str],
    stored: tuple[bytes, AnalyzerRunResult],
) -> None:
    config_bytes, result = stored
    if getattr(spec, "inputs", INPUTS_FILENAMES) != INPUTS_FILENAMES or result.errors:
        return
    original_by_posix = {_repo_relative_posix(path, repo_root): path for path in files}
    by_path: dict[str, list[Finding]] = {path: [] for path in files}
    for finding in result.findings:
        original = original_by_posix.get(
            _repo_relative_posix(finding.path, repo_root)
        )
        if original is not None:
            by_path[original].append(finding)
    for file_path, findings in by_path.items():
        _write_entry(
            _entry_path(repo_root, spec.name, file_path, config_bytes), findings
        )


def _entry_path(
    repo_root: Path, analyzer_name: str, file_path: str, config_bytes: bytes
) -> Path:
    file_bytes = _file_bytes(repo_root, file_path)
    key = fingerprint(
        (analyzer_name.encode(), file_path.encode(), file_bytes, config_bytes)
    )
    return cache_root(repo_root) / analyzer_name / f"{key}.json"


def _repo_relative_posix(path: str, repo_root: Path) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        return candidate.as_posix()
    resolved = candidate.resolve()
    relative = _path_inside(resolved, repo_root.resolve())
    return relative if relative is not None else resolved.as_posix()


def _path_inside(resolved: Path, root: Path) -> str | None:
    try:
        relative = Path(os.path.relpath(resolved, root))
    except ValueError:
        return None
    if relative.parts[:1] == ("..",):
        return None
    return relative.as_posix()


def _file_bytes(repo_root: Path, file_path: str) -> bytes:
    path = repo_root / file_path
    if not path.is_file():
        return b""
    return path.read_bytes()


def _read_entry(
    repo_root: Path, analyzer_name: str, file_path: str, config_bytes: bytes
) -> list[Finding] | None:
    path = _entry_path(repo_root, analyzer_name, file_path, config_bytes)
    if not path.is_file():
        return None
    return _findings_in_cache(path)


def _findings_in_cache(path: Path) -> list[Finding] | None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return None
    findings: list[Finding] = []
    for item in raw:
        parsed = _cached_finding(item)
        if parsed is None:
            return None
        findings.append(parsed)
    return findings


def _cached_finding(item: object) -> Finding | None:
    if not isinstance(item, dict):
        return None
    return Finding(
        path=str(item["path"]),
        line=int(item["line"]),
        rule_id=str(item["rule_id"]),
        message=str(item["message"]),
    )


def _write_entry(path: Path, findings: list[Finding]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                {
                    "path": item.path,
                    "line": item.line,
                    "rule_id": item.rule_id,
                    "message": item.message,
                }
                for item in findings
            ]
        ),
        encoding="utf-8",
    )
