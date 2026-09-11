from __future__ import annotations

from pathlib import Path


def resolve_repo_path(repo_root: Path, relative_path: str) -> Path:
    root = repo_root.resolve()
    path = (root / relative_path).resolve()
    path.relative_to(root)
    if not path.exists():
        raise FileNotFoundError(path)
    return path
