from pathlib import Path
import subprocess
from types import SimpleNamespace
import zipfile

import pytest

from pyslop.cli import main
from pyslop import runner as runner_module
from pyslop.discovery import DiscoveryOptions
from pyslop.rules_loader import RulesError, load_rules
from pyslop.runner import RunnerDependencies, inspect_analyzers, run
from pyslop.scaffold import ScaffoldError, ScaffoldResult, scaffold, scaffold_extensions
from pyslop.types import (
    AnalyzerConfig,
    AnalyzerRunResult,
    AnalyzerSpec,
    PyslopConfig,
    ExtensionConfig,
    Finding,
    RuleMetadata,
    RunOptions,
    RunResult,
)

ERROR_EXIT_CODE = 2
ALL_MODE_EXPECTED_IN_REPO_FINDINGS = 2


# Why this test survives refactoring: scaffold creates the documented default Agent Skills setup.
def test_scaffold_creates_agents_skill_and_config(tmp_path: Path) -> None:
    result = scaffold(tmp_path)

    assert tmp_path / ".agents" / "skills" / "pyslop" / "SKILL.md" in result.created
    assert tmp_path / "pyslop.toml" in result.created
    assert (
        tmp_path / ".pyslop" / "analyzers" / "ruff" / "config.toml"
        not in result.created
    )
    skill_path = tmp_path / ".agents" / "skills" / "pyslop" / "SKILL.md"
    assert skill_path.exists()
    assert (tmp_path / "pyslop.toml").exists()
    template = (
        Path(__file__).resolve().parents[1]
        / "pyslop"
        / "templates"
        / "defaults"
        / "skills"
        / "pyslop"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert skill_path.read_text(encoding="utf-8") == template


# Why this test survives refactoring: Claude is the only init path that is not .agents/skills.
def test_scaffold_creates_claude_skill_target(tmp_path: Path) -> None:
    claude = scaffold(tmp_path / "claude", "claude")

    assert (
        tmp_path / "claude" / ".claude" / "skills" / "pyslop" / "SKILL.md"
        in claude.created
    )
    assert not (tmp_path / "claude" / ".agents" / "skills").exists()


# Why this test survives refactoring: non-overwrite behavior protects user-authored setup.
def test_scaffold_does_not_overwrite_existing_files(tmp_path: Path) -> None:
    skill = tmp_path / ".agents" / "skills" / "pyslop" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("existing", encoding="utf-8")
    (tmp_path / "pyslop.toml").write_text("existing-config", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".pyslop/cache/\n", encoding="utf-8")

    result = scaffold(tmp_path)

    assert skill not in result.created
    assert (tmp_path / "pyslop.toml") not in result.created
    assert skill.read_text(encoding="utf-8") == "existing"
    assert (tmp_path / "pyslop.toml").read_text(encoding="utf-8") == "existing-config"


# Why this test survives refactoring: overwrite behavior allows users to replace corrupted or old files.
def test_scaffold_overwrites_existing_files_when_requested(tmp_path: Path) -> None:
    skill = tmp_path / ".agents" / "skills" / "pyslop" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("existing", encoding="utf-8")

    # Add an extraneous file that should NOT be reported as created
    extraneous = tmp_path / ".agents" / "skills" / "pyslop" / "other.md"
    extraneous.write_text("other", encoding="utf-8")

    (tmp_path / "pyslop.toml").write_text("existing-config", encoding="utf-8")

    result = scaffold(tmp_path, overwrite=True)

    assert skill in result.created
    assert (tmp_path / "pyslop.toml") in result.created
    assert extraneous not in result.created

    assert skill.read_text(encoding="utf-8") != "existing"
    assert (tmp_path / "pyslop.toml").read_text(encoding="utf-8") != "existing-config"
    # Make sure extraneous file was left untouched
    assert extraneous.read_text(encoding="utf-8") == "other"


# Why this test survives refactoring: init writes a stub overlay, not a forked rule corpus.
def test_scaffold_init_does_not_copy_packaged_analyzer_rules(tmp_path: Path) -> None:
    result = scaffold(tmp_path)

    assert (tmp_path / "pyslop.toml").exists()
    assert not (tmp_path / ".pyslop" / "analyzers").exists()
    assert result.created


# Why this test survives refactoring: pyslop.toml template is overlay-first, not a corpus copy.
def test_scaffold_init_pyslop_toml_is_stub_overlay(tmp_path: Path) -> None:
    scaffold(tmp_path)

    config = (tmp_path / "pyslop.toml").read_text(encoding="utf-8")
    assert "[analyzers]" in config
    assert "Packaged analyzer configs" in config
    assert not (tmp_path / ".pyslop" / "analyzers").exists()


# Why this test survives refactoring: init and extensions are separate user-facing concerns.
def test_scaffold_init_does_not_create_extension_files(tmp_path: Path) -> None:
    scaffold(tmp_path)

    assert not (tmp_path / "pyslop_extensions").exists()


# Why this test survives refactoring: extensions command has an all-installed tracer path.
def test_scaffold_extensions_installs_all_when_no_names_given(tmp_path: Path) -> None:
    scaffold(tmp_path)

    scaffold_extensions(tmp_path)

    assert (tmp_path / "pyslop_extensions" / "detect_shims" / "__init__.py").exists()
    assert (tmp_path / "pyslop_extensions" / "detect_shims" / "analyzer.py").exists()
    assert (tmp_path / "pyslop_extensions" / "detect_shims" / "rules.toml").exists()
    assert not (tmp_path / "pyslop_extensions" / "slop_words").exists()


# Why this test survives refactoring: named extension install lets users opt into a subset.
def test_scaffold_extensions_installs_only_named_extension(tmp_path: Path) -> None:
    scaffold(tmp_path)

    scaffold_extensions(tmp_path, ("detect-shims",))

    assert (tmp_path / "pyslop_extensions" / "detect_shims" / "__init__.py").exists()
    assert (tmp_path / "pyslop_extensions" / "detect_shims" / "analyzer.py").exists()
    assert not (tmp_path / "pyslop_extensions" / "slop_words").exists()


# Why this test survives refactoring: standalone extension install requires init-created config.
def test_scaffold_extensions_errors_when_pyslop_toml_missing(tmp_path: Path) -> None:
    with pytest.raises(ScaffoldError) as excinfo:
        scaffold_extensions(tmp_path)
    assert "pyslop.toml not found" in str(excinfo.value)


# Why this test survives refactoring: unknown extension names should fail fast for user feedback.
def test_scaffold_extensions_errors_on_unknown_extension_name(tmp_path: Path) -> None:
    scaffold(tmp_path)

    with pytest.raises(ScaffoldError) as excinfo:
        scaffold_extensions(tmp_path, ("not-real",))
    assert str(excinfo.value) == "Unknown extension name(s): not-real"


# Why this test survives refactoring: extension registration must be idempotent.
def test_scaffold_extensions_skips_toml_append_when_extension_already_registered(
    tmp_path: Path,
) -> None:
    scaffold(tmp_path)
    scaffold_extensions(tmp_path, ("detect-shims",))

    scaffold_extensions(tmp_path, ("detect-shims",))

    config = (tmp_path / "pyslop.toml").read_text(encoding="utf-8")
    assert config.count('id = "detect-shims"') == 1


# Why this test survives refactoring: extension scaffold must preserve user edits by default.
def test_scaffold_extensions_preserves_existing_files_without_overwrite(
    tmp_path: Path,
) -> None:
    scaffold(tmp_path)
    analyzer_path = tmp_path / "pyslop_extensions" / "detect_shims" / "analyzer.py"
    analyzer_path.parent.mkdir(parents=True, exist_ok=True)
    analyzer_path.write_text("# user edit\n", encoding="utf-8")

    scaffold_extensions(tmp_path, ("detect-shims",))

    assert analyzer_path.read_text(encoding="utf-8") == "# user edit\n"


# Why this test survives refactoring: overwrite remains the repair path for stale extension files.
def test_scaffold_extensions_overwrites_existing_files_when_requested(
    tmp_path: Path,
) -> None:
    scaffold(tmp_path)
    analyzer_path = tmp_path / "pyslop_extensions" / "detect_shims" / "analyzer.py"
    analyzer_path.parent.mkdir(parents=True, exist_ok=True)
    analyzer_path.write_text("# user edit\n", encoding="utf-8")

    scaffold_extensions(tmp_path, ("detect-shims",), overwrite=True)

    assert analyzer_path.read_text(encoding="utf-8") != "# user edit\n"
    assert "def analyze" in analyzer_path.read_text(encoding="utf-8")


# Why this test survives refactoring: init must gitignore the cache directory.
def test_scaffold_creates_gitignore_with_cache_entry_when_missing(
    tmp_path: Path,
) -> None:
    result = scaffold(tmp_path)

    gitignore = tmp_path / ".gitignore"
    assert gitignore.exists()
    assert gitignore.read_text(encoding="utf-8") == ".pyslop/cache/\n"
    assert gitignore in result.created


# Why this test survives refactoring: init should append ignore entry without clobbering user rules.
def test_scaffold_appends_cache_entry_to_existing_gitignore(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("*.pyc\n", encoding="utf-8")

    scaffold(tmp_path)

    assert gitignore.read_text(encoding="utf-8") == "*.pyc\n.pyslop/cache/\n"


# Why this test survives refactoring: repeat init runs should not duplicate ignore entries.
def test_scaffold_does_not_duplicate_cache_entry_when_already_present(
    tmp_path: Path,
) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(".pyslop/cache/\n", encoding="utf-8")

    scaffold(tmp_path)

    assert gitignore.read_text(encoding="utf-8") == ".pyslop/cache/\n"


# Why this test survives refactoring: packaged init must not wire Data Studio Reflex plugins.
def test_scaffold_init_toml_does_not_register_reflex_plugins(tmp_path: Path) -> None:
    scaffold(tmp_path)
    config = (tmp_path / "pyslop.toml").read_text(encoding="utf-8")
    assert "reflex-state-lock" not in config
    assert "reflex-laggy-input" not in config


# Why this test survives refactoring: the installed wheel must ship skill and analyzer templates.
# Requires `uv` on PATH (`uv build --wheel`).
def test_built_wheel_contains_skill_and_ruff_config(tmp_path: Path) -> None:
    package_root = Path(__file__).resolve().parents[1]
    dist = tmp_path / "dist"
    dist.mkdir()
    subprocess.run(
        [
            "uv",
            "build",
            "--wheel",
            "--out-dir",
            str(dist),
        ],
        cwd=package_root,
        check=True,
    )
    wheels = list(dist.glob("pyslop-*.whl"))
    assert wheels
    names = zipfile.ZipFile(wheels[0]).namelist()
    assert any(path.endswith("templates/defaults/skills/pyslop/SKILL.md") for path in names)
    assert any(
        "templates/defaults/analyzers/ruff/config.toml" in path for path in names
    )

