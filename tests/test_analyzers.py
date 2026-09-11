from collections.abc import Sequence
from pathlib import Path
import json
import subprocess
import sys
from subprocess import CompletedProcess

from pyslop.analyzers import complexipy, detect_secrets, mypy, pylint, ruff, vulture
from pyslop.analyzers.base import CommandSpec, run_command, tool_command
from pyslop.analyzers.extension import run_one_extension
from pyslop.analyzers.registry import (
    BUILTIN_ANALYZERS,
    analyzers_for_run,
    get_enabled_analyzers,
    stages_for_run,
)
from pyslop.types import (
    STAGE_CI,
    AnalyzerConfig,
    AnalyzerRunResult,
    AnalyzerSpec,
    PyslopConfig,
    ExtensionConfig,
    Finding,
    RuleMetadata,
)


# Why this test survives refactoring: analyzer availability is exposed as enabled analyzer names.
def test_get_enabled_analyzers_returns_all_available_builtins() -> None:
    analyzers = get_enabled_analyzers(PyslopConfig(), available=lambda name: True)

    assert [analyzer.name for analyzer in analyzers] == list(BUILTIN_ANALYZERS)


# Why this test survives refactoring: disabled config is a public selection rule.
def test_get_enabled_analyzers_excludes_disabled_tools() -> None:
    config = PyslopConfig(disabled_analyzers=frozenset({"ruff"}))

    analyzers = get_enabled_analyzers(config, available=lambda name: True)

    assert "ruff" not in [analyzer.name for analyzer in analyzers]


# Why this test survives refactoring: missing tools are silently skipped for callers.
def test_get_enabled_analyzers_silently_excludes_unavailable_tools() -> None:
    analyzers = get_enabled_analyzers(PyslopConfig(), available=lambda name: False)

    assert analyzers == []


# Why this test survives refactoring: analyzer availability is exposed through enabled analyzer names.
def test_get_enabled_analyzers_includes_detect_secrets_when_hook_available() -> None:
    analyzers = get_enabled_analyzers(
        PyslopConfig(),
        available=lambda name: name == "detect-secrets-hook",
    )

    assert [analyzer.name for analyzer in analyzers] == ["detect-secrets"]


# Why this test survives refactoring: importable modules are not enough to select a builtin.
def test_get_enabled_analyzers_excludes_detect_secrets_when_hook_missing() -> None:
    analyzers = get_enabled_analyzers(
        PyslopConfig(),
        available=lambda name: False,
    )

    assert analyzers == []


# Why this test survives refactoring: existing builtin availability still uses each analyzer name.
def test_get_enabled_analyzers_keeps_existing_builtin_name_resolution() -> None:
    analyzers = get_enabled_analyzers(
        PyslopConfig(),
        available=lambda name: name == "ruff",
    )

    assert [analyzer.name for analyzer in analyzers] == ["ruff"]


# Why this test survives refactoring: builtin pylint is CI-only in the public spec.
def test_get_enabled_analyzers_marks_pylint_ci() -> None:
    # Arrange / Act
    analyzers = get_enabled_analyzers(
        PyslopConfig(),
        available=lambda name: name == "pylint",
    )

    # Assert
    assert analyzers == [
        AnalyzerSpec(name="pylint", stage="ci"),
    ]


# Why this test survives refactoring: pylint's enabled message set is the public CI contract.
def test_packaged_pylint_config_enables_only_cyclic_import() -> None:
    # Arrange
    config_path = (
        Path(__file__).resolve().parents[1]
        / "pyslop"
        / "templates"
        / "defaults"
        / "analyzers"
        / "pylint"
        / "config.toml"
    )
    text = config_path.read_text(encoding="utf-8")

    # Assert
    assert "cyclic-import" in text
    assert "import-error" not in text
    assert "too-many-lines" not in text
    assert "consider-using-join" not in text


# Why this test survives refactoring: default runs must omit CI-only analyzers including pylint and index extensions.
def test_analyzers_for_run_skips_ci_stage_on_default() -> None:
    # Arrange
    config = PyslopConfig(
        extensions=(
            ExtensionConfig(
                id="lock",
                entry_point="ext.py:analyze",
                stage=STAGE_CI,
                inputs="index",
                index_roots=("pkg/",),
            ),
            ExtensionConfig(
                id="words",
                entry_point="words.py:analyze",
            ),
        )
    )

    # Act
    selected = analyzers_for_run(
        config,
        stages_for_run(None),
        available=lambda name: True,
    )
    names = [spec.name for spec in selected]

    # Assert
    assert "pylint" not in names
    assert "lock" not in names
    assert "words" in names
    assert "ruff" in names
    assert "regex" not in names


# Why this test survives refactoring: --stage ci must add CI-only pylint and index extensions.
def test_analyzers_for_run_includes_ci_stage_when_requested() -> None:
    # Arrange
    config = PyslopConfig(
        extensions=(
            ExtensionConfig(
                id="lock",
                entry_point="ext.py:analyze",
                stage=STAGE_CI,
                inputs="index",
                index_roots=("pkg/",),
            ),
        )
    )

    # Act
    selected = analyzers_for_run(
        config,
        stages_for_run("ci"),
        available=lambda name: name == "pylint",
    )

    # Assert
    assert [spec.name for spec in selected] == ["pylint", "lock"]


# Why this test survives refactoring: regex is selected only when detect rules exist.
def test_analyzers_for_run_includes_regex_when_detect_rules_exist() -> None:
    selected = analyzers_for_run(
        PyslopConfig(),
        stages_for_run(None),
        available=lambda name: False,
        rules={
            "slop-words.todo": RuleMetadata(
                "slop-words.todo", detect_kind="regex", pattern="todo"
            )
        },
    )

    assert [spec.name for spec in selected] == ["regex"]


# Why this test survives refactoring: the normalized ruff Finding contract is public.
def test_ruff_parse_output_normalizes_json_findings() -> None:
    raw = '[{"filename":"app/a.py","location":{"row":4},"code":"PLR0913","message":"Too many arguments"}]'

    findings = ruff.parse_output(raw)

    assert findings == [Finding("app/a.py", 4, "ruff-PLR0913", "Too many arguments")]


# Why this test survives refactoring: native console scripts must beat python -m startup.
def test_tool_command_uses_executable_when_on_path(monkeypatch) -> None:
    # Arrange
    monkeypatch.setattr(
        "pyslop.analyzers.base.shutil.which",
        lambda _name: r"C:\bin\ruff.exe",
    )

    # Act
    command = tool_command("ruff", "check")

    # Assert
    assert command == [r"C:\bin\ruff.exe", "check"]


# Why this test survives refactoring: missing binaries still run via the interpreter module.
def test_tool_command_falls_back_to_python_module_when_executable_missing(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setattr("pyslop.analyzers.base.shutil.which", lambda _name: None)

    # Act
    command = tool_command("ruff", "check")

    # Assert
    assert command == [sys.executable, "-m", "ruff", "check"]


# Why this test survives refactoring: detect-secrets JSON normalization is the analyzer contract.
def test_detect_secrets_parse_output_normalizes_single_file_json() -> None:
    raw = (
        '{"results": {"app/key.py": [{"type": "AWS Access Key", '
        '"filename": "app/key.py", "hashed_secret": "abc", '
        '"is_verified": false, "line_number": 42}]}}'
    )

    findings = detect_secrets.parse_output(raw)

    assert findings == [Finding("app/key.py", 42, "secrets", "AWS Access Key detected")]


# Why this test survives refactoring: each detect-secrets result entry is a user-visible finding.
def test_detect_secrets_parse_output_normalizes_multiple_file_json() -> None:
    raw = (
        '{"results": {'
        '"app/key.py": [{"type": "AWS Access Key", "filename": "app/key.py", '
        '"line_number": 42}], '
        '"config.yaml": [{"type": "Private Key", "filename": "config.yaml", '
        '"line_number": 3}]'
        "}}"
    )

    findings = detect_secrets.parse_output(raw)

    assert findings == [
        Finding("app/key.py", 42, "secrets", "AWS Access Key detected"),
        Finding("config.yaml", 3, "secrets", "Private Key detected"),
    ]


# Why this test survives refactoring: clean detect-secrets output should produce no findings.
def test_detect_secrets_parse_output_returns_empty_list_without_results() -> None:
    findings = detect_secrets.parse_output('{"results": {}}')

    assert findings == []


# Why this test survives refactoring: empty stdout is a valid no-findings analyzer output.
def test_detect_secrets_parse_output_returns_empty_list_for_empty_input() -> None:
    findings = detect_secrets.parse_output("")

    assert findings == []


# Why this test survives refactoring: run exposes command behavior without requiring a real subprocess.
def test_detect_secrets_run_builds_json_command_and_returns_findings() -> None:
    executor = RecordingExecutor(
        '{"results": {"app/key.py": [{"type": "AWS Access Key", '
        '"filename": "app/key.py", "line_number": 42}]}}',
        1,
    )

    result = detect_secrets.run(
        ["app/key.py"], Path("."), AnalyzerConfig(), executor.run
    )

    assert executor.command == ("detect-secrets-hook", "--json", "app/key.py")
    assert result.findings == (
        Finding("app/key.py", 42, "secrets", "AWS Access Key detected"),
    )


# Why this test survives refactoring: analyzer config is translated into documented CLI flags.
def test_detect_secrets_run_appends_baseline_from_config(tmp_path: Path) -> None:
    config_path = tmp_path / "detect-secrets.toml"
    config_path.write_text('baseline = ".secrets.baseline"\n', encoding="utf-8")
    executor = RecordingExecutor('{"results": {}}', 0)

    detect_secrets.run(
        ["app/key.py"],
        tmp_path,
        AnalyzerConfig(config=str(config_path)),
        executor.run,
    )

    assert "--baseline" in executor.command
    assert ".secrets.baseline" in executor.command


# Why this test survives refactoring: each disabled detector is passed as its own CLI flag.
def test_detect_secrets_run_appends_disabled_plugins_from_config(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "detect-secrets.toml"
    config_path.write_text(
        'disable_plugins = ["KeywordDetector", "Base64HighEntropyString"]\n',
        encoding="utf-8",
    )
    executor = RecordingExecutor('{"results": {}}', 0)

    detect_secrets.run(
        ["app/key.py"],
        tmp_path,
        AnalyzerConfig(config=str(config_path)),
        executor.run,
    )

    assert executor.command == (
        "detect-secrets-hook",
        "--json",
        "--disable-plugin",
        "KeywordDetector",
        "--disable-plugin",
        "Base64HighEntropyString",
        "app/key.py",
    )


# Why this test survives refactoring: tool/config failures must become result errors for CLI mapping.
def test_detect_secrets_run_records_tool_error_for_usage_failure() -> None:
    result = detect_secrets.run(
        ["app/key.py"],
        Path("."),
        AnalyzerConfig(),
        RecordingExecutor("", 3, "bad config").run,
    )

    assert result.errors == ("detect-secrets failed with exit code 3: bad config",)
    assert result.findings == ()


# Why this test survives refactoring: crash entries must not leak into user reports.
def test_pylint_parse_output_filters_crash_entries() -> None:
    raw = """[
{"path":"app/a.py","line":2,"symbol":"unused-import","message":"Unused import"},
{"path":"app/b.py","line":1,"symbol":"fatal","message":"fatal error while checking app/b.py"}
]"""

    findings = pylint.parse_output(raw)

    assert findings == [Finding("app/a.py", 2, "unused-import", "Unused import")]


# Why this test survives refactoring: pylint R0801 JSON path can point at an unrelated module; pyslop re-attributes using message participants.
def test_pylint_run_reattributes_misassigned_duplicate_code_path(
    tmp_path: Path,
) -> None:
    # Arrange
    (tmp_path / "app" / "features").mkdir(parents=True)
    (tmp_path / "app" / "features" / "one.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "app" / "features" / "two.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "noise.py").write_text("# unrelated\n", encoding="utf-8")
    msg = (
        "Similar lines in 2 files\n"
        "==app.features.one:[1:1]\n"
        "==app.features.two:[1:1]\n"
        "    x = 1"
    )
    raw = json.dumps(
        [
            {
                "path": str(tmp_path / "noise.py"),
                "line": 1,
                "symbol": "duplicate-code",
                "message": msg,
            }
        ]
    )
    executor = RecordingExecutor(raw, 8)

    # Act
    result = pylint.run(
        ["app/features/one.py", "app/features/two.py", "noise.py"],
        tmp_path,
        AnalyzerConfig(),
        executor.run,
    )

    # Assert
    assert result.findings == (
        Finding("app/features/one.py", 1, "duplicate-code", msg),
    )


# Why this test survives refactoring: mypy text normalization is part of the parser interface.
def test_mypy_parse_output_normalizes_error_code() -> None:
    raw = 'app/a.py:8:3: error: Argument 1 has incompatible type "str" [arg-type]'

    findings = mypy.parse_output(raw)

    assert findings == [
        Finding(
            "app/a.py",
            8,
            "mypy-error[arg-type]",
            'error: Argument 1 has incompatible type "str"',
        )
    ]


# Why this test survives refactoring: mypy should run in one batch with explicit package bases to avoid basename module collisions.
def test_mypy_run_uses_explicit_package_base_batch_command(tmp_path: Path) -> None:
    # Arrange
    executor = RecordingExecutor("", 0)

    # Act
    result = mypy.run(
        ["app/one.py", "app/two.py"], tmp_path, AnalyzerConfig(), executor.run
    )

    # Assert
    assert result == AnalyzerRunResult()
    assert "--explicit-package-bases" in executor.command
    assert "--namespace-packages" in executor.command
    assert executor.command[-2:] == (
        "app/one.py",
        "app/two.py",
    )


# Why this test survives refactoring: vulture whitelists suppress false positives in the report.
def test_vulture_run_appends_whitelist_from_config_directory(tmp_path: Path) -> None:
    config_dir = tmp_path / ".pyslop" / "analyzers"
    config_dir.mkdir(parents=True)
    (config_dir / "vulture.toml").write_text("[tool.vulture]\n", encoding="utf-8")
    (config_dir / "vulture_whitelist.py").write_text(
        "unused_func  # noqa\n", encoding="utf-8"
    )
    executor = RecordingExecutor("", 0)

    vulture.run(
        ["app/a.py"],
        tmp_path,
        AnalyzerConfig(config=str(config_dir / "vulture.toml")),
        executor.run,
    )

    assert str(config_dir / "vulture_whitelist.py") in executor.command


# Why this test survives refactoring: repo-root whitelist is used when no config-level whitelist exists.
def test_vulture_run_appends_whitelist_from_repo_root(tmp_path: Path) -> None:
    (tmp_path / "vulture_whitelist.py").write_text(
        "unused_func  # noqa\n", encoding="utf-8"
    )
    executor = RecordingExecutor("", 0)

    vulture.run(["app/a.py"], tmp_path, AnalyzerConfig(), executor.run)

    assert str(tmp_path / "vulture_whitelist.py") in executor.command


# Why this test survives refactoring: no whitelist should not break the command.
def test_vulture_run_works_without_whitelist(tmp_path: Path) -> None:
    executor = RecordingExecutor("", 0)

    vulture.run(["app/a.py"], tmp_path, AnalyzerConfig(), executor.run)

    assert "vulture_whitelist.py" not in " ".join(executor.command)


# Why this test survives refactoring: Python-only analyzers should not treat configs as Python.
def test_pylint_run_filters_non_python_targets(tmp_path: Path) -> None:
    executor = RecordingExecutor("[]", 0)

    pylint.run(
        ["app/a.py", "rules/secrets.toml"], tmp_path, AnalyzerConfig(), executor.run
    )

    assert "--output-format=json" in executor.command
    assert executor.command[-1] == "app/a.py"
    assert "rules/secrets.toml" not in executor.command


# Why this test survives refactoring: Python-only analyzers should not run non-Python-only batches.
def test_vulture_run_skips_non_python_only_targets(tmp_path: Path) -> None:
    result = vulture.run(
        ["rules/secrets.toml"], tmp_path, AnalyzerConfig(), FailingExecutor().run
    )

    assert result == AnalyzerRunResult()


# Why this test survives refactoring: vulture confidence should remain in the report message.
def test_vulture_parse_output_appends_confidence() -> None:
    raw = "app/a.py:12: unused function 'legacy' (90% confidence)"

    findings = vulture.parse_output(raw)

    assert findings == [
        Finding("app/a.py", 12, "vulture", "unused function 'legacy' (90% confidence)")
    ]


# Why this test survives refactoring: complexipy JSON output normalization is public.
def test_complexipy_parse_output_reports_exceeded_functions() -> None:
    raw = '[{"path":"app/a.py","line":22,"function":"build","complexity":17,"threshold":15}]'

    findings = complexipy.parse_output(raw)

    assert findings == [
        Finding(
            "app/a.py",
            22,
            "complexipy",
            "`build` has cognitive complexity of 17 (threshold 15)",
        )
    ]


# Why this test survives refactoring: complexipy config is translated into supported CLI options.
def test_complexipy_run_translates_toml_config_to_supported_flags(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "complexipy.toml"
    config_path.write_text(
        """[tool.complexipy]
max-complexity-allowed = 12
exclude = ["tests/**"]
""",
        encoding="utf-8",
    )
    executor = RecordingExecutor("[]", 0)

    complexipy.run(
        ["app/a.py"],
        tmp_path,
        AnalyzerConfig(config=str(config_path)),
        executor.run,
    )

    assert "--config" not in executor.command
    assert "--max-complexity-allowed" in executor.command
    assert "12" in executor.command
    assert "--exclude" in executor.command
    assert "tests/**" in executor.command


# Why this test survives refactoring: run exposes command behavior without requiring a real subprocess.
def test_ruff_run_forwards_custom_config_path() -> None:
    executor = RecordingExecutor(
        '[{"filename":"app/a.py","location":{"row":4},"code":"PLR0913","message":"Too many arguments"}]',
        1,
    )

    result = ruff.run(
        ["app/a.py"], Path("."), AnalyzerConfig(config="custom-ruff.toml"), executor.run
    )

    assert result.findings == (
        Finding("app/a.py", 4, "ruff-PLR0913", "Too many arguments"),
    )
    assert "--config" in executor.command
    assert "custom-ruff.toml" in executor.command


# Why this test survives refactoring: tool/config failures must become result errors for CLI mapping.
def test_ruff_run_records_tool_error_for_usage_failure() -> None:
    result = ruff.run(
        ["app/a.py"],
        Path("."),
        AnalyzerConfig(),
        RecordingExecutor("", 2, "bad config").run,
    )

    assert result.errors == ("ruff failed with exit code 2: bad config",)


# Why this test survives refactoring: command extensions use the documented JSON stdout contract.
def test_run_extension_analyzers_collects_command_findings(tmp_path: Path) -> None:
    config = PyslopConfig(
        extensions=(ExtensionConfig(id="custom", command=("python", "audit.py")),)
    )
    executor = RecordingExecutor(
        '[{"path":"app/a.py","line":1,"rule_id":"custom","message":"Issue"}]', 1
    )

    result = run_one_extension(
        config.extensions[0], ["app/a.py"], tmp_path, executor.run
    )

    assert executor.command[-1] == "app/a.py"
    assert result.findings == (Finding("app/a.py", 1, "custom", "Issue"),)


# Why this test survives refactoring: command extensions expose behavior only through subprocess arguments and JSON output.
def test_run_extension_analyzers_does_not_pass_config_to_command_extension(
    tmp_path: Path,
) -> None:
    # Arrange
    config = PyslopConfig(
        extensions=(
            ExtensionConfig(
                id="custom",
                command=("python", "audit.py"),
                config="custom.toml",
            ),
        )
    )
    executor = RecordingExecutor("[]", 0)

    # Act
    run_one_extension(config.extensions[0], ["app/a.py"], tmp_path, executor.run)

    # Assert
    assert executor.command == ("python", "audit.py", "app/a.py")


# Why this test survives refactoring: entry-point extensions compose after command extensions.
def test_run_extension_analyzers_collects_entry_point_findings_after_commands(
    tmp_path: Path,
) -> None:
    config = PyslopConfig(
        extensions=(
            ExtensionConfig(id="command", command=("python", "audit.py")),
            ExtensionConfig(
                id="entry", entry_point="tests.test_analyzers:entry_extension"
            ),
        )
    )
    executor = RecordingExecutor(
        '[{"path":"app/a.py","line":1,"rule_id":"command","message":"Command"}]', 0
    )

    command = run_one_extension(
        config.extensions[0], ["app/a.py"], tmp_path, executor.run
    )
    entry = run_one_extension(config.extensions[1], ["app/a.py"], tmp_path)

    assert command.findings + entry.findings == (
        Finding("app/a.py", 1, "command", "Command"),
        Finding("app/a.py", 2, "entry", "Entry"),
    )


# Why this test survives refactoring: file entry points are observed through public extension findings.
def test_run_extension_analyzers_invokes_repo_relative_file_entry_point(
    tmp_path: Path,
) -> None:
    # Arrange
    extension_path = tmp_path / "extensions" / "custom.py"
    extension_path.parent.mkdir(parents=True)
    extension_path.write_text(
        """
from pathlib import Path

from pyslop.types import Finding


def analyze(files: list[str], repo_root: Path, config_path: str | None) -> list[Finding]:
    return [Finding(files[0], 4, "custom", repo_root.name)]
""",
        encoding="utf-8",
    )
    config = PyslopConfig(
        extensions=(
            ExtensionConfig(id="custom", entry_point="extensions/custom.py:analyze"),
        )
    )

    # Act
    result = run_one_extension(config.extensions[0], ["app/a.py"], tmp_path)

    # Assert
    assert result.findings == (Finding("app/a.py", 4, "custom", tmp_path.name),)


# Why this test survives refactoring: unsafe file entry points are exposed as extension errors.
def test_run_extension_analyzers_rejects_file_entry_point_outside_repo(
    tmp_path: Path,
) -> None:
    # Arrange
    outside_path = tmp_path.parent / "outside_extension.py"
    outside_path.write_text(
        "def analyze(files, repo_root, config_path):\n    return []\n",
        encoding="utf-8",
    )
    config = PyslopConfig(
        extensions=(
            ExtensionConfig(id="custom", entry_point="../outside_extension.py:analyze"),
        )
    )

    # Act
    result = run_one_extension(config.extensions[0], ["app/a.py"], tmp_path)

    # Assert
    assert result.findings == ()
    assert len(result.errors) == 1
    assert result.errors[0].startswith("extension custom failed:")


# Why this test survives refactoring: missing file entry points are isolated as extension errors.
def test_run_extension_analyzers_records_error_for_missing_file_entry_point(
    tmp_path: Path,
) -> None:
    # Arrange
    config = PyslopConfig(
        extensions=(
            ExtensionConfig(id="custom", entry_point="extensions/missing.py:analyze"),
        )
    )

    # Act
    result = run_one_extension(config.extensions[0], ["app/a.py"], tmp_path)

    # Assert
    assert result.findings == ()
    assert len(result.errors) == 1
    assert result.errors[0].startswith("extension custom failed:")


# Why this test survives refactoring: missing functions are visible through extension errors.
def test_run_extension_analyzers_records_error_for_missing_file_function(
    tmp_path: Path,
) -> None:
    # Arrange
    extension_path = tmp_path / "extensions" / "custom.py"
    extension_path.parent.mkdir(parents=True)
    extension_path.write_text("VALUE = 1\n", encoding="utf-8")
    config = PyslopConfig(
        extensions=(
            ExtensionConfig(id="custom", entry_point="extensions/custom.py:analyze"),
        )
    )

    # Act
    result = run_one_extension(config.extensions[0], ["app/a.py"], tmp_path)

    # Assert
    assert result.findings == ()
    assert len(result.errors) == 1
    assert result.errors[0].startswith("extension custom failed:")


# Why this test survives refactoring: entry-point extensions expose received inputs through returned findings.
def test_run_extension_analyzers_passes_config_path_to_entry_point(
    tmp_path: Path,
) -> None:
    # Arrange
    config = PyslopConfig(
        extensions=(
            ExtensionConfig(
                id="entry",
                entry_point="tests.test_analyzers:entry_extension_with_config",
                config="custom.toml",
            ),
        )
    )

    # Act
    result = run_one_extension(config.extensions[0], ["app/a.py"], tmp_path)

    # Assert
    assert result.findings == (Finding("app/a.py", 3, "entry", "custom.toml"),)


# Why this test survives refactoring: disabled analyzer ids are a public selection rule for extensions.
def test_run_extension_analyzers_skips_disabled_extension_id(
    tmp_path: Path,
) -> None:
    # Arrange
    config = PyslopConfig(
        disabled_analyzers=frozenset({"custom"}),
        extensions=(ExtensionConfig(id="custom", command=("python", "audit.py")),),
    )

    # Act
    selected = analyzers_for_run(
        config, stages_for_run(None), available=lambda name: False
    )

    # Act / Assert
    assert "custom" not in [spec.name for spec in selected]


# Why this test survives refactoring: bad extensions should not stop later extensions.
def test_run_extension_analyzers_records_errors_and_continues(tmp_path: Path) -> None:
    config = PyslopConfig(
        extensions=(
            ExtensionConfig(id="bad", command=("python", "bad.py")),
            ExtensionConfig(
                id="entry", entry_point="tests.test_analyzers:entry_extension"
            ),
        )
    )
    executor = RecordingExecutor("not json", 2, "broken")

    bad = run_one_extension(config.extensions[0], ["app/a.py"], tmp_path, executor.run)
    entry = run_one_extension(config.extensions[1], ["app/a.py"], tmp_path)

    assert bad.errors == ("extension bad failed with exit code 2: broken",)
    assert entry.findings == (Finding("app/a.py", 2, "entry", "Entry"),)


# Why this test survives refactoring: project-scoped extension findings must be filtered to discovered files.
def test_run_extension_analyzers_filters_findings_to_discovered_files(
    tmp_path: Path,
) -> None:
    config = PyslopConfig(
        extensions=(ExtensionConfig(id="custom", command=("python", "audit.py")),)
    )
    executor = RecordingExecutor(
        '[{"path":"app/a.py","line":1,"rule_id":"custom","message":"Kept"},'
        '{"path":"app/b.py","line":2,"rule_id":"custom","message":"Dropped"}]',
        0,
    )

    result = run_one_extension(
        config.extensions[0], ["app/a.py"], tmp_path, executor.run
    )

    assert result.findings == (
        Finding("app/a.py", 1, "custom", "Kept"),
        Finding("app/b.py", 2, "custom", "Dropped"),
    )


# Why this test survives refactoring: executor crashes must be scoped to the failing analyzer.
def test_run_command_returns_error_when_executor_times_out() -> None:
    # Arrange
    def timeout_executor(_command: Sequence[str]) -> CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=["ruff"], timeout=300)

    spec = CommandSpec(
        name="ruff",
        command=("ruff", "check", "."),
        parse_output=lambda _raw: [],
    )

    # Act
    result = run_command(spec, timeout_executor)

    # Assert
    assert result.findings == ()
    assert result.errors == ("ruff timed out after 300s",)


# Why this test survives refactoring: parser failures should produce user-visible analyzer errors.
def test_run_command_returns_error_when_parser_raises() -> None:
    # Arrange
    def successful_executor(command: Sequence[str]) -> CompletedProcess[str]:
        return CompletedProcess(command, 0, stdout="{", stderr="")

    def parse_output(_raw: str) -> list[Finding]:
        raise ValueError("bad json")

    spec = CommandSpec(
        name="ruff",
        command=("ruff", "check", "."),
        parse_output=parse_output,
    )

    # Act
    result = run_command(spec, successful_executor)

    # Assert
    assert result.findings == ()
    assert result.errors == ("ruff produced unparseable output: bad json",)


# Why this test survives refactoring: missing executables skip instead of failing the run.
def test_run_command_skips_when_executable_is_missing() -> None:
    def missing_executor(_command: Sequence[str]) -> CompletedProcess[str]:
        raise FileNotFoundError("complexipy")

    spec = CommandSpec(
        name="complexipy",
        command=("complexipy", "."),
        parse_output=lambda _raw: [],
    )

    result = run_command(spec, missing_executor)

    assert result.findings == ()
    assert result.errors == ()
    assert result.skipped == (("complexipy", "executable not on PATH"),)


_EXPECTED_SEPARATE_EXTENSION_COMMAND_COUNT = 1


# Why this test survives refactoring: command extensions receive the full file list in one process.
def test_run_extension_analyzers_invokes_command_once_for_large_file_lists(
    tmp_path: Path,
) -> None:
    files = ["a" * 30 + ".py", "b" * 30 + ".py", "c" * 30 + ".py"]
    config = PyslopConfig(
        extensions=(ExtensionConfig(id="custom", command=("python", "audit.py")),)
    )
    executor = MultiRecordingExecutor()

    result = run_one_extension(config.extensions[0], files, tmp_path, executor.run)

    assert len(executor.commands) == _EXPECTED_SEPARATE_EXTENSION_COMMAND_COUNT
    assert executor.commands[0][-3:] == tuple(files)


class RecordingExecutor:
    def __init__(self, stdout: str, returncode: int, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr
        self.command: tuple[str, ...] = ()

    def run(self, command: Sequence[str]) -> CompletedProcess[str]:
        self.command = tuple(command)
        return CompletedProcess(
            command, self.returncode, stdout=self.stdout, stderr=self.stderr
        )


class FailingExecutor:
    def run(self, command: Sequence[str]) -> CompletedProcess[str]:
        raise AssertionError(f"analyzer should not be invoked: {command}")


class MultiRecordingExecutor:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: Sequence[str]) -> CompletedProcess[str]:
        self.commands.append(tuple(command))
        file_path = command[-1]
        return CompletedProcess(
            command,
            0,
            stdout=f'[{{"path":"{file_path}","line":1,"rule_id":"custom","message":"Issue"}}]',
            stderr="",
        )


def entry_extension(
    files: list[str], _repo_root: Path, config_path: str | None
) -> list[Finding]:
    return [Finding(files[0], 2, "entry", "Entry")]


def entry_extension_with_config(
    files: list[str], _repo_root: Path, config_path: str | None
) -> list[Finding]:
    return [Finding(files[0], 3, "entry", str(config_path))]
