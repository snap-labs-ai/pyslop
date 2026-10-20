from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

TEST_ROOT_NAMES = frozenset({"tests", "testing"})


@dataclass(frozen=True)
class RootPackage:
    name: str
    directory: Path
    is_test: bool


def discover_root_packages(repo_root: Path) -> tuple[RootPackage, ...]:
    found: list[RootPackage] = []
    found.extend(_packages_in(repo_root))
    src = repo_root / "src"
    if src.is_dir() and not src.name.startswith("."):
        found.extend(_packages_in(src))
    return tuple(found)


def _packages_in(parent: Path) -> list[RootPackage]:
    packages: list[RootPackage] = []
    try:
        children = sorted(parent.iterdir(), key=lambda path: path.name)
    except OSError:
        return packages
    for child in children:
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        if not child.is_dir():
            continue
        if not (child / "__init__.py").is_file():
            continue
        packages.append(
            RootPackage(
                name=child.name,
                directory=child,
                is_test=child.name in TEST_ROOT_NAMES,
            )
        )
    return packages
