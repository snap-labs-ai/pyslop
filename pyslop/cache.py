from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pyslop.types import AnalyzerRunResult, Finding, INPUTS_FILENAMES, AnalyzerSpec

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
    config_bytes: bytes,
    result: AnalyzerRunResult,
) -> None:
    if getattr(spec, "inputs", INPUTS_FILENAMES) != INPUTS_FILENAMES or result.errors:
        return
    by_path: dict[str, list[Finding]] = {path: [] for path in files}
    for finding in result.findings:
        if finding.path in by_path:
            by_path[finding.path].append(finding)
    for file_path, findings in by_path.items():
        _write_entry(repo_root, spec.name, file_path, config_bytes, findings)


def _entry_path(
    repo_root: Path, analyzer_name: str, file_path: str, config_bytes: bytes
) -> Path:
    file_bytes = _file_bytes(repo_root, file_path)
    key = fingerprint(
        (analyzer_name.encode(), file_path.encode(), file_bytes, config_bytes)
    )
    return cache_root(repo_root) / analyzer_name / f"{key}.json"


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
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return None
    findings: list[Finding] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        findings.append(
            Finding(
                path=str(item["path"]),
                line=int(item["line"]),
                rule_id=str(item["rule_id"]),
                message=str(item["message"]),
            )
        )
    return findings


def _write_entry(
    repo_root: Path,
    analyzer_name: str,
    file_path: str,
    config_bytes: bytes,
    findings: list[Finding],
) -> None:
    path = _entry_path(repo_root, analyzer_name, file_path, config_bytes)
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
