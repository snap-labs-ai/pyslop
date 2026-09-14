from __future__ import annotations

import fnmatch
import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess

from pyslop.types import DiscoveryModeFields


class DiscoveryError(Exception):
    """Raised when git discovery cannot run."""


GitExecutor = Callable[[Sequence[str]], CompletedProcess[str]]


@dataclass(frozen=True, kw_only=True)
class DiscoveryOptions(DiscoveryModeFields):
    excludes: tuple[str, ...] = ()


def apply_excludes(
    files: list[str], patterns: list[str] | tuple[str, ...]
) -> list[str]:
    if not patterns:
        return files
    return [path for path in files if not _matches_any(path, patterns)]


def discover_files(
    repo_root: Path,
    options: DiscoveryOptions,
    executor: GitExecutor | None = None,
) -> list[str]:
    files = (
        _discover_explicit(repo_root, options)
        if options.all_files or options.files
        else _discover_git(repo_root, options, executor or _run_git)
    )
    existing = [path for path in _unique(files) if (repo_root / path).is_file()]
    visible = [path for path in existing if not is_dot_path(path)]
    filtered = _filter_for_path(visible, options.path)
    return (
        filtered if options.no_exclude else apply_excludes(filtered, options.excludes)
    )


def _discover_explicit(repo_root: Path, options: DiscoveryOptions) -> list[str]:
    if options.files:
        candidates: list[Path] = []
        for explicit_target in options.files:
            root = repo_root / explicit_target
            if root.is_file():
                candidates.append(root)
                continue
            if root.is_dir():
                candidates.extend(_walk_visible_files(root))
                continue
            candidates.append(root)
    else:
        candidates = _walk_visible_files(repo_root)
    return [_relative(repo_root, path) for path in candidates if path.is_file()]


def _discover_git(
    repo_root: Path, options: DiscoveryOptions, executor: GitExecutor
) -> list[str]:
    _ = repo_root
    _require_git_work_tree(executor)
    uncommitted = _git_uncommitted(executor)
    if options.uncommitted_only:
        return uncommitted
    base = _git_lines(
        executor,
        ["git", "diff", "--name-only", "--diff-filter=d", f"{options.base}...HEAD"],
    )
    return [*base, *uncommitted]


def _require_git_work_tree(executor: GitExecutor) -> None:
    try:
        result = executor(["git", "rev-parse", "--is-inside-work-tree"])
    except FileNotFoundError as exc:
        raise DiscoveryError(
            "git discovery could not run: git is not available"
        ) from exc
    except CalledProcessError as exc:
        raise DiscoveryError(
            "git discovery could not run: not a git repository"
        ) from exc
    if result.returncode != 0:
        raise DiscoveryError("git discovery could not run: not a git repository")
    marker = (result.stdout or "").strip().lower()
    if marker and marker not in {"true", "1"}:
        raise DiscoveryError("git discovery could not run: not a git repository")


def _git_uncommitted(executor: GitExecutor) -> list[str]:
    return [
        *_git_lines(executor, ["git", "diff", "--name-only", "--diff-filter=d"]),
        *_git_lines(
            executor, ["git", "diff", "--cached", "--name-only", "--diff-filter=d"]
        ),
        *_git_lines(executor, ["git", "ls-files", "--others", "--exclude-standard"]),
    ]


def _git_lines(executor: GitExecutor, command: list[str]) -> list[str]:
    try:
        result = executor(command)
    except CalledProcessError:
        return []
    return [
        line.strip().replace("\\", "/")
        for line in result.stdout.splitlines()
        if line.strip()
    ]


def _run_git(command: Sequence[str]) -> CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, check=True, text=True)
    except FileNotFoundError as exc:
        raise DiscoveryError(
            "git discovery could not run: git is not available"
        ) from exc


def _unique(files: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in files:
        normalized = path.replace("\\", "/")
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _filter_for_path(files: list[str], path: str) -> list[str]:
    if not path:
        return files
    normalized = path.replace("\\", "/").strip("/")
    return [
        file
        for file in files
        if file == normalized or file.startswith(f"{normalized}/")
    ]


def _matches_any(path: str, patterns: list[str] | tuple[str, ...]) -> bool:
    normalized = path.replace("\\", "/")
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns)


def _relative(repo_root: Path, path: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def is_dot_path(path: str) -> bool:
    return any(
        _is_dot_name(part) for part in path.replace("\\", "/").split("/") if part
    )


def _is_dot_name(name: str) -> bool:
    return name.startswith(".") and name not in {".", ".."}


def _walk_visible_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for current, dirnames, filenames in os.walk(root, topdown=True):
        dirnames[:] = [name for name in dirnames if not _is_dot_name(name)]
        current_path = Path(current)
        for name in filenames:
            if _is_dot_name(name):
                continue
            found.append(current_path / name)
    return sorted(found)
