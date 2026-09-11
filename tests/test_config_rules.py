from pathlib import Path
import tempfile

import pytest

from pyslop.packaged import load_packaged_rules
from pyslop.config import ConfigError, load_config
from pyslop.rules_loader import RulesError, load_rules
from pyslop.types import AnalyzerConfig, PyslopConfig, ExtensionConfig


# Why this test survives refactoring: it checks the public default config contract, not parser internals.
def test_load_config_returns_defaults_when_no_file_exists(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    assert config.exclude == ()
    assert config.disabled_analyzers == frozenset()
    assert config.extensions == ()


# Why this test survives refactoring: every setting is verified through typed config data.
def test_load_config_reads_repo_settings_from_pyslop_toml_only(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pyslop]\nexclude = ['ignored/**']\n", encoding="utf-8"
    )
    (tmp_path / "pyslop.toml").write_text(
        """
exclude = ["alembic/**"]

[analyzers]
disable = ["ruff"]

[analyzers.ruff]
config = "custom-ruff.toml"

[[analyzers.extensions]]
id = "state-lock"
command = ["python", "scripts/audit_state_locks.py"]
rules = "rules/state-lock.toml"

[[analyzers.extensions]]
id = "entry"
entry-point = "pkg.audit:run"
rules = "rules/entry.toml"

[rules.custom-rule]
name = "Custom Rule"
fix = "Fix it."
doc-links = ["https://example.com"]
""",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config.exclude == ("alembic/**",)
    assert config.disabled_analyzers == frozenset({"ruff"})
    assert config.analyzer_configs["ruff"].config == "custom-ruff.toml"
    assert config.extensions[0].command == ("python", "scripts/audit_state_locks.py")
    assert config.extensions[0].rules == "rules/state-lock.toml"
    assert config.extensions[1].entry_point == "pkg.audit:run"
    assert config.extensions[1].rules == "rules/entry.toml"
    assert config.rules["custom-rule"].fix == "Fix it."


# Why this test survives refactoring: unknown detect kinds are a public configuration error.
def test_load_config_rejects_unknown_detect_kind(tmp_path: Path) -> None:
    (tmp_path / "pyslop.toml").write_text(
        """
[[rules]]
id = "custom.ast"
detect = { kind = "ast", pattern = "unused" }
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="detect.kind"):
        load_config(tmp_path)


# Why this test survives refactoring: select and ignore are the public finding-filter contract.
def test_load_config_reads_select_and_ignore(tmp_path: Path) -> None:
    (tmp_path / "pyslop.toml").write_text(
        """
select = ["ruff-*", "slop-words.*"]
ignore = ["ruff-PLR0913"]
""",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config.select == ("ruff-*", "slop-words.*")
    assert config.ignore == ("ruff-PLR0913",)


# Why this test survives refactoring: overlay fix text wins for an existing packaged rule id.
def test_load_rules_overlay_fix_wins_for_packaged_rule_id(tmp_path: Path) -> None:
    config = load_config_from_text(
        """
[rules."slop-words.todo"]
fix = "Overlay fix."
"""
    )

    rules = load_rules(config, repo_root=tmp_path)

    assert rules["slop-words.todo"].fix == "Overlay fix."
    assert rules["slop-words.todo"].detect_kind == "regex"
    assert rules["slop-words.todo"].pattern


# Why this test survives refactoring: extension config paths are observed through load_config's typed result.
def test_load_config_exposes_extension_config_path_for_entry_point(
    tmp_path: Path,
) -> None:
    # Arrange
    (tmp_path / "pyslop.toml").write_text(
        """
[[analyzers.extensions]]
id = "slop-words"
entry-point = "pyslop_extensions/slop_words/analyzer.py:analyze"
config = "pyslop_extensions/slop_words/config.toml"
""",
        encoding="utf-8",
    )

    # Act
    config = load_config(tmp_path)

    # Assert
    assert config.extensions[0].config == "pyslop_extensions/slop_words/config.toml"


# Why this test survives refactoring: command extension defaults are verified through typed config data.
def test_load_config_defaults_command_extension_config_to_none(
    tmp_path: Path,
) -> None:
    # Arrange
    (tmp_path / "pyslop.toml").write_text(
        """
[[analyzers.extensions]]
id = "state-lock"
command = ["python", "scripts/audit_state_locks.py"]
""",
        encoding="utf-8",
    )

    # Act
    config = load_config(tmp_path)

    # Assert
    assert config.extensions[0].command == ("python", "scripts/audit_state_locks.py")
    assert config.extensions[0].config is None


# Why this test survives refactoring: extension config schema failures are part of the public parser contract.
def test_load_config_raises_typed_error_for_non_string_extension_config(
    tmp_path: Path,
) -> None:
    # Arrange
    (tmp_path / "pyslop.toml").write_text(
        """
[[analyzers.extensions]]
id = "slop-words"
entry-point = "pyslop_extensions/slop_words/analyzer.py:analyze"
config = ["not", "a", "string"]
""",
        encoding="utf-8",
    )

    # Act / Assert
    with pytest.raises(ConfigError):
        load_config(tmp_path)


# Why this test survives refactoring: callers depend on ConfigError for CLI exit-code mapping.
def test_load_config_raises_typed_error_for_invalid_toml(tmp_path: Path) -> None:
    (tmp_path / "pyslop.toml").write_text("exclude = [", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(tmp_path)


# Why this test survives refactoring: schema validation is observed through the typed public error.
def test_load_config_raises_typed_error_for_schema_violations(tmp_path: Path) -> None:
    (tmp_path / "pyslop.toml").write_text("exclude = 'not-a-list'\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(tmp_path)


# Why this test survives refactoring: without configured paths, the loader returns no metadata.
def test_load_rules_returns_empty_without_configured_paths() -> None:
    rules = load_rules()

    assert rules == {}


# Why this test survives refactoring: inline rules are the highest-precedence metadata override.
def test_load_rules_prefers_inline_over_analyzer_rules(tmp_path: Path) -> None:
    rules_path = tmp_path / ".pyslop" / "analyzers" / "ruff" / "rules.toml"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text(
        """
[rules.ruff-F401]
name = "workspace-name"
fix = "Workspace fix."
""",
        encoding="utf-8",
    )
    config = PyslopConfig(
        analyzer_configs={
            "ruff": AnalyzerConfig(rules=".pyslop/analyzers/ruff/rules.toml")
        },
        rules=load_config_from_text(
            """
[rules.ruff-F401]
name = "inline-name"
fix = "Inline fix."
doc-links = ["https://repo.example"]
"""
        ).rules,
    )

    rules = load_rules(config, repo_root=tmp_path)

    assert rules["ruff-F401"].name == "inline-name"
    assert rules["ruff-F401"].fix == "Inline fix."


# Why this test survives refactoring: additive repo rules must enrich matching findings.
def test_load_rules_adds_repo_only_rules(tmp_path: Path) -> None:
    config = load_config_from_text(
        """
[rules.local-rule]
name = "local"
fix = "Local fix."
"""
    )

    rules = load_rules(config, repo_root=tmp_path)

    assert rules["local-rule"].name == "local"
    assert rules["local-rule"].fix == "Local fix."


# Why this test survives refactoring: extension rule files are observed through public rule metadata.
def test_load_rules_adds_registered_extension_rules(tmp_path: Path) -> None:
    # Arrange
    rules_path = tmp_path / "rules" / "extension.toml"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text(
        """
[rules.extension-rule]
name = "Extension Rule"
fix = "Fix from extension."
""",
        encoding="utf-8",
    )
    config = PyslopConfig(
        extensions=(
            ExtensionConfig(
                id="custom",
                command=("python", "audit.py"),
                rules="rules/extension.toml",
            ),
        )
    )

    # Act
    rules = load_rules(config, repo_root=tmp_path)

    # Assert
    assert rules["extension-rule"].name == "Extension Rule"
    assert rules["extension-rule"].fix == "Fix from extension."


# Why this test survives refactoring: missing configured rule files are public configuration errors.
def test_load_rules_raises_typed_error_for_missing_extension_rules(
    tmp_path: Path,
) -> None:
    # Arrange
    config = PyslopConfig(
        extensions=(
            ExtensionConfig(
                id="custom",
                command=("python", "audit.py"),
                rules="rules/missing.toml",
            ),
        )
    )

    # Act / Assert
    with pytest.raises(RulesError, match="rules/missing.toml"):
        load_rules(config, repo_root=tmp_path)


# Why this test survives refactoring: unsafe rule paths are rejected through the public loader.
def test_load_rules_raises_typed_error_for_extension_rules_outside_repo(
    tmp_path: Path,
) -> None:
    # Arrange
    config = PyslopConfig(
        extensions=(
            ExtensionConfig(
                id="custom",
                command=("python", "audit.py"),
                rules="../rules.toml",
            ),
        )
    )

    # Act / Assert
    with pytest.raises(RulesError, match="../rules.toml"):
        load_rules(config, repo_root=tmp_path)


# Why this test survives refactoring: inline repo rules have documented precedence over extension rules.
def test_load_rules_prefers_inline_rules_over_extension_rules(tmp_path: Path) -> None:
    # Arrange
    rules_path = tmp_path / "rules" / "extension.toml"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text(
        """
[rules.shared-rule]
name = "Extension Rule"
fix = "Fix from extension."
""",
        encoding="utf-8",
    )
    config = PyslopConfig(
        extensions=(
            ExtensionConfig(
                id="custom",
                command=("python", "audit.py"),
                rules="rules/extension.toml",
            ),
        ),
        rules={
            "shared-rule": load_config_from_text(
                """
[rules.shared-rule]
name = "Inline Rule"
fix = "Fix inline."
"""
            ).rules["shared-rule"]
        },
    )

    # Act
    rules = load_rules(config, repo_root=tmp_path)

    # Assert
    assert rules["shared-rule"].name == "Inline Rule"
    assert rules["shared-rule"].fix == "Fix inline."


# Why this test survives refactoring: it validates the public entry-point extension config contract.
def test_load_config_reads_reflex_state_lock_entry_point_extension(
    tmp_path: Path,
) -> None:
    # Arrange
    (tmp_path / "pyslop.toml").write_text(
        """
[[analyzers.extensions]]
id = "reflex-state-lock"
entry-point = "pyslop_extensions/reflex_state_lock/analyzer.py:analyze"
rules = "pyslop_extensions/reflex_state_lock/rules.toml"
""",
        encoding="utf-8",
    )

    # Act
    config = load_config(tmp_path)

    # Assert
    extension = config.extensions[0]
    assert extension.id == "reflex-state-lock"
    assert (
        extension.entry_point
        == "pyslop_extensions/reflex_state_lock/analyzer.py:analyze"
    )
    assert extension.command == ()
    assert extension.rules == "pyslop_extensions/reflex_state_lock/rules.toml"


# Why this test survives refactoring: it verifies extension rule metadata is loaded through the public rules loader.
def test_load_rules_reads_reflex_state_lock_rule_metadata(tmp_path: Path) -> None:
    # Arrange
    rules_path = tmp_path / "pyslop_extensions" / "reflex_state_lock" / "rules.toml"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text(
        """
[rules.state-lock-ap1]
name = "I/O under implicit lock"
fix = "Move awaited I/O out of regular @rx.event handlers or convert to a background event with minimal locked sections."
""",
        encoding="utf-8",
    )
    config = PyslopConfig(
        extensions=(
            ExtensionConfig(
                id="reflex-state-lock",
                entry_point="pyslop_extensions/reflex_state_lock/analyzer.py:analyze",
                rules="pyslop_extensions/reflex_state_lock/rules.toml",
            ),
        )
    )

    # Act
    rules = load_rules(config, repo_root=tmp_path)

    # Assert
    assert rules["state-lock-ap1"].name == "I/O under implicit lock"


# Why this test survives refactoring: stage and inputs are the public extension scheduling contract.
@pytest.mark.parametrize(
    ("stage", "inputs", "index_roots_toml"),
    [
        ("pre-commit", "filenames", ""),
        ("ci", "index", 'index-roots = ["pkg/"]\n'),
        ("always", "filenames", ""),
    ],
)
def test_load_config_accepts_allowed_extension_stage_and_inputs(
    tmp_path: Path, stage: str, inputs: str, index_roots_toml: str
) -> None:
    # Arrange
    (tmp_path / "pyslop.toml").write_text(
        f"""
[[analyzers.extensions]]
id = "custom"
entry-point = "ext.py:analyze"
stage = "{stage}"
inputs = "{inputs}"
{index_roots_toml}
""",
        encoding="utf-8",
    )

    # Act
    config = load_config(tmp_path)

    # Assert
    assert config.extensions[0].stage == stage
    assert config.extensions[0].inputs == inputs


# Why this test survives refactoring: index analyzers must declare readable roots or config is invalid.
def test_load_config_rejects_index_extension_without_index_roots(
    tmp_path: Path,
) -> None:
    # Arrange
    (tmp_path / "pyslop.toml").write_text(
        """
[[analyzers.extensions]]
id = "custom"
entry-point = "ext.py:analyze"
inputs = "index"
""",
        encoding="utf-8",
    )

    # Act / Assert
    with pytest.raises(ConfigError, match="index-roots"):
        load_config(tmp_path)


# Why this test survives refactoring: invalid stage values are a public config error.
def test_load_config_rejects_unknown_extension_stage(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "pyslop.toml").write_text(
        """
[[analyzers.extensions]]
id = "custom"
entry-point = "ext.py:analyze"
stage = "nightly"
""",
        encoding="utf-8",
    )

    # Act / Assert
    with pytest.raises(ConfigError, match="stage"):
        load_config(tmp_path)


# Why this test survives refactoring: serial is not a supported extension contract.
def test_load_config_rejects_extension_serial(tmp_path: Path) -> None:
    (tmp_path / "pyslop.toml").write_text(
        """
[[analyzers.extensions]]
id = "custom"
entry-point = "ext.py:analyze"
serial = true
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="serial"):
        load_config(tmp_path)


# Why this test survives refactoring: packaged slop-words share markdown ignores.
def test_packaged_regex_rules_ignore_markdown() -> None:
    rules = load_packaged_rules()
    slop = [rule for rule_id, rule in rules.items() if rule_id.startswith("slop-words.")]
    assert slop
    for rule in slop:
        assert "**/*.md" in rule.ignore


def load_config_from_text(text: str) -> PyslopConfig:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "pyslop.toml").write_text(text, encoding="utf-8")
        return load_config(root)
