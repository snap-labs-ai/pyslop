from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

CONFIG_TEMPLATE = """# Pyslop configuration
# Packaged analyzer configs and regex rules apply unless you overlay paths.

exclude = []
# select = ["ruff-*"]
# ignore = ["slop-words.temp"]

[analyzers]
disable = []
"""

CACHE_GITIGNORE_ENTRY = ".pyslop/cache/"


@dataclass(frozen=True)
class ScaffoldResult:
    created: tuple[Path, ...]


@dataclass(frozen=True)
class BundledExtension:
    template_dir: str
    toml_block: str


class ScaffoldError(Exception):
    """Raised when scaffold inputs are invalid."""


BUNDLED_EXTENSIONS: dict[str, BundledExtension] = {
    "detect-shims": BundledExtension(
        template_dir="detect_shims",
        toml_block="""[[analyzers.extensions]]
id = "detect-shims"
entry-point = "pyslop_extensions/detect_shims/analyzer.py:analyze"
rules = "pyslop_extensions/detect_shims/rules.toml"
stage = "always"
inputs = "filenames"
""",
    ),
}


def scaffold(
    repo_root: Path,
    target: str | None = None,
    overwrite: bool = False,
) -> ScaffoldResult:
    skills_target_root = _skills_target_root(repo_root, target)
    config_path = repo_root / "pyslop.toml"
    created: list[Path] = []
    created.extend(_scaffold_skills(skills_target_root, overwrite))
    if not config_path.exists() or overwrite:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        created.append(config_path)
    gitignore = _ensure_cache_gitignore_entry(repo_root)
    if gitignore:
        created.append(gitignore)
    return ScaffoldResult(created=tuple(created))


def _skills_target_root(repo_root: Path, target: str | None) -> Path:
    if target == "cursor":
        return repo_root / ".cursor" / "skills"
    if target == "claude":
        return repo_root / ".claude" / "skills"
    return repo_root / ".agents" / "skills"


def _scaffold_skills(target_root: Path, overwrite: bool = False) -> list[Path]:
    created: list[Path] = []
    for skill_dir in sorted(
        _skills_template_root().iterdir(), key=lambda path: path.name
    ):
        if not skill_dir.is_dir():
            continue
        created.extend(
            _copy_template_files(
                skill_dir, target_root / skill_dir.name, Path(), overwrite
            )
        )
    return created


def scaffold_extensions(
    repo_root: Path, names: tuple[str, ...] = (), overwrite: bool = False
) -> ScaffoldResult:
    config_path = repo_root / "pyslop.toml"
    if not config_path.exists():
        raise ScaffoldError("pyslop.toml not found. Run pyslop init first.")
    extension_ids = _selected_extension_ids(names)
    created: list[Path] = []
    for extension_id in extension_ids:
        extension = BUNDLED_EXTENSIONS[extension_id]
        source_root = resources.files("pyslop").joinpath(
            "templates", "defaults", "pyslop_extensions", extension.template_dir
        )
        destination_root = repo_root / "pyslop_extensions" / extension.template_dir
        created.extend(
            _copy_template_files(source_root, destination_root, Path(), overwrite)
        )
    if _append_extension_blocks(config_path, extension_ids):
        created.append(config_path)
    return ScaffoldResult(created=tuple(created))


def _selected_extension_ids(names: tuple[str, ...]) -> tuple[str, ...]:
    if not names:
        return tuple(sorted(BUNDLED_EXTENSIONS))
    unknown = sorted(name for name in names if name not in BUNDLED_EXTENSIONS)
    if unknown:
        unknown_names = ", ".join(unknown)
        raise ScaffoldError(f"Unknown extension name(s): {unknown_names}")
    # Preserve user order while deduplicating.
    return tuple(dict.fromkeys(names))


def _append_extension_blocks(config_path: Path, extension_ids: tuple[str, ...]) -> bool:
    config_text = config_path.read_text(encoding="utf-8")
    updated_text = config_text
    for extension_id in extension_ids:
        extension = BUNDLED_EXTENSIONS[extension_id]
        marker = f'id = "{extension_id}"'
        if marker in updated_text:
            continue
        if not updated_text.endswith("\n"):
            updated_text = f"{updated_text}\n"
        updated_text = f"{updated_text}\n{extension.toml_block}"
    if updated_text == config_text:
        return False
    config_path.write_text(updated_text, encoding="utf-8")
    return True


def _copy_template_files(
    source: Traversable | Path,
    destination_root: Path,
    relative_path: Path,
    overwrite: bool,
) -> list[Path]:
    created: list[Path] = []
    for item in sorted(source.iterdir(), key=lambda child: child.name):
        child_relative_path = relative_path / item.name
        if item.is_dir():
            created.extend(
                _copy_template_files(
                    item, destination_root, child_relative_path, overwrite
                )
            )
            continue
        destination = destination_root / child_relative_path
        if destination.exists() and not overwrite:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(item.read_bytes())
        created.append(destination)
    return created


def _ensure_cache_gitignore_entry(repo_root: Path) -> Path | None:
    gitignore_path = repo_root / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(f"{CACHE_GITIGNORE_ENTRY}\n", encoding="utf-8")
        return gitignore_path

    existing_content = gitignore_path.read_text(encoding="utf-8")
    existing_lines = existing_content.splitlines()
    if CACHE_GITIGNORE_ENTRY in existing_lines:
        return None

    separator = "\n" if existing_content and not existing_content.endswith("\n") else ""
    updated_content = f"{existing_content}{separator}{CACHE_GITIGNORE_ENTRY}\n"
    gitignore_path.write_text(updated_content, encoding="utf-8")
    return gitignore_path


def _skills_template_root() -> Traversable:
    return resources.files("pyslop").joinpath("templates", "defaults", "skills")
