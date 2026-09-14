from pathlib import Path
from types import SimpleNamespace
import tempfile

import pytest

from pyslop.cli import main
from pyslop import runner as runner_module
from pyslop.discovery import DiscoveryOptions
from pyslop.rules_loader import RulesError, load_rules
from pyslop.packaged import packaged_analyzer_config
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


# Why this test survives refactoring: it observes the runner AXI stdout and exit-code contract.
def test_runner_writes_axi_stdout_and_returns_findings_exit_code(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text("print('x')", encoding="utf-8")

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["app.py"]

    def run_analyzers(
        _config: PyslopConfig, _files: list[str], _root: Path
    ) -> AnalyzerRunResult:
        return AnalyzerRunResult((Finding("app.py", 1, "custom", "Issue"),))

    def load_rules(_config: PyslopConfig, _repo_root: Path) -> dict[str, RuleMetadata]:
        return {"custom": RuleMetadata("custom", "Custom", "Fix it.", ())}

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        run_analyzers=run_analyzers,
        load_rules=load_rules,
    )

    result = run(RunOptions(repo_root=tmp_path), deps)

    assert result.exit_code == 0
    assert result.findings_count == 1
    assert result.files_with_findings_count == 1
    assert result.stdout_text is not None
    assert "custom" in result.stdout_text
    assert "Fix it." in result.stdout_text

# Why this test survives refactoring: select/ignore filter findings after analyzers.
def test_runner_drops_findings_by_select_and_ignore(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('x')", encoding="utf-8")

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig(ignore=("ruff-PLR0913",))

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["app.py"]

    def run_analyzers(
        _config: PyslopConfig, _files: list[str], _root: Path
    ) -> AnalyzerRunResult:
        return AnalyzerRunResult(
            (
                Finding("app.py", 1, "ruff-PLR0913", "too many args"),
                Finding("app.py", 2, "ruff-F401", "unused"),
            )
        )

    def load_rules(_config: PyslopConfig, _repo_root: Path) -> dict[str, RuleMetadata]:
        return {}

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        run_analyzers=run_analyzers,
        load_rules=load_rules,
    )

    ignored = run(RunOptions(repo_root=tmp_path), deps)
    assert ignored.findings_count == 1
    assert ignored.stdout_text is not None
    assert "ruff-F401" in ignored.stdout_text
    assert "ruff-PLR0913" not in ignored.stdout_text

    def load_select(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig(select=("slop-words.*",))

    selected = run(
        RunOptions(repo_root=tmp_path),
        RunnerDependencies(
            load_config=load_select,
            discover_files=discover_files,
            run_analyzers=run_analyzers,
            load_rules=load_rules,
        ),
    )
    assert selected.findings_count == 0


# Why this test survives refactoring: stdout mode is a public runner output contract.
def test_runner_returns_stdout_text_for_findings(
    tmp_path: Path,
) -> None:
    # Arrange
    (tmp_path / "app.py").write_text("print('x')", encoding="utf-8")

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["app.py"]

    def run_analyzers(
        _config: PyslopConfig, _files: list[str], _root: Path
    ) -> AnalyzerRunResult:
        return AnalyzerRunResult((Finding("app.py", 1, "custom", "Issue"),))

    def load_rules(_config: PyslopConfig, _repo_root: Path) -> dict[str, RuleMetadata]:
        return {"custom": RuleMetadata("custom", fix="Fix it.")}

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        run_analyzers=run_analyzers,
        load_rules=load_rules,
    )

    # Act
    result = run(RunOptions(repo_root=tmp_path), deps)

    # Assert
    assert result.exit_code == 0
    assert result.stdout_text is not None
    assert "custom" in result.stdout_text
    assert "Fix it." in result.stdout_text


# Why this test survives refactoring: clean stdout mode should produce AXI empty-state text.
def test_runner_returns_no_stdout_text_when_clean(
    tmp_path: Path,
) -> None:
    # Arrange
    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return []

    def run_analyzers(
        _config: PyslopConfig, _files: list[str], _root: Path
    ) -> AnalyzerRunResult:
        return AnalyzerRunResult()

    def load_rules(_config: PyslopConfig, _repo_root: Path) -> dict[str, RuleMetadata]:
        return {}

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        run_analyzers=run_analyzers,
        load_rules=load_rules,
    )

    # Act
    result = run(RunOptions(repo_root=tmp_path), deps)

    # Assert
    assert result.exit_code == 0
    assert result.stdout_text is not None
    assert "findings: 0 in this file set" in result.stdout_text

# Why this test survives refactoring: analyzer errors must preserve partial stdout findings.
def test_runner_returns_stdout_text_with_errors(
    tmp_path: Path,
) -> None:
    # Arrange
    (tmp_path / "app.py").write_text("print('x')", encoding="utf-8")

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["app.py"]

    def run_analyzers(
        _config: PyslopConfig, _files: list[str], _root: Path
    ) -> AnalyzerRunResult:
        return AnalyzerRunResult(
            findings=(Finding("app.py", 1, "custom", "Issue"),),
            errors=("bad config",),
        )

    def load_rules(_config: PyslopConfig, _repo_root: Path) -> dict[str, RuleMetadata]:
        return {}

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        run_analyzers=run_analyzers,
        load_rules=load_rules,
    )

    # Act
    result = run(RunOptions(repo_root=tmp_path), deps)

    # Assert
    assert result.exit_code == ERROR_EXIT_CODE
    assert result.errors == ("bad config",)
    assert result.stdout_text is not None
    assert "error: bad config" in result.stdout_text

# Why this test survives refactoring: clean AXI runs have a distinct public exit code and body.
def test_runner_returns_zero_when_clean(tmp_path: Path) -> None:
    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return []

    def run_analyzers(
        _config: PyslopConfig, _files: list[str], _root: Path
    ) -> AnalyzerRunResult:
        return AnalyzerRunResult()

    def load_rules(_config: PyslopConfig, _repo_root: Path) -> dict[str, RuleMetadata]:
        return {}

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        run_analyzers=run_analyzers,
        load_rules=load_rules,
    )

    result = run(RunOptions(repo_root=tmp_path), deps)

    assert result.exit_code == 0
    assert result.stdout_text is not None
    assert "findings: 0 in this file set" in result.stdout_text


# Why this test survives refactoring: config/tool failures map to the documented CLI error exit code.
def test_runner_returns_error_exit_code_for_tool_errors(tmp_path: Path) -> None:
    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["app.py"]

    def run_analyzers(
        _config: PyslopConfig, _files: list[str], _root: Path
    ) -> AnalyzerRunResult:
        return AnalyzerRunResult(errors=("bad config",))

    def load_rules(_config: PyslopConfig, _repo_root: Path) -> dict[str, RuleMetadata]:
        return {}

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        run_analyzers=run_analyzers,
        load_rules=load_rules,
    )

    result = run(RunOptions(repo_root=tmp_path), deps)

    assert result.exit_code == ERROR_EXIT_CODE
    assert result.errors == ("bad config",)


# Why this test survives refactoring: rules configuration failures use the public run error contract.
def test_runner_returns_error_exit_code_for_extension_rules_errors(
    tmp_path: Path,
) -> None:
    # Arrange
    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig(
            extensions=(
                ExtensionConfig(
                    id="custom",
                    command=("python", "audit.py"),
                    rules="rules/missing.toml",
                ),
            )
        )

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return []

    def run_analyzers(
        _config: PyslopConfig, _files: list[str], _root: Path
    ) -> AnalyzerRunResult:
        return AnalyzerRunResult()

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        run_analyzers=run_analyzers,
    )

    # Act
    result = run(RunOptions(repo_root=tmp_path), deps)

    # Assert
    assert result.exit_code == ERROR_EXIT_CODE
    assert "rules/missing.toml" in result.errors[0]


# Why this test survives refactoring: --strict is the public findings gate.
def test_runner_strict_exits_one_when_findings_exist(tmp_path: Path) -> None:
    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["app.py"]

    def run_analyzers(
        _config: PyslopConfig, _files: list[str], _root: Path
    ) -> AnalyzerRunResult:
        return AnalyzerRunResult((Finding("app.py", 1, "custom", "Issue"),))

    def load_rules(_config: PyslopConfig, _repo_root: Path) -> dict[str, RuleMetadata]:
        return {}

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        run_analyzers=run_analyzers,
        load_rules=load_rules,
    )
    (tmp_path / "app.py").write_text("print('x')", encoding="utf-8")

    result = run(RunOptions(repo_root=tmp_path, strict=True), deps)

    assert result.exit_code == 1
    assert result.findings_count == 1


# Why this test survives refactoring: mode options must be visible to discovery as typed options.
def test_runner_forwards_mode_selection_to_discovery(tmp_path: Path) -> None:
    captured: dict[str, str | bool | tuple[str, ...] | None] = {}

    def capture_discovery(_root: Path, options: DiscoveryOptions) -> list[str]:
        captured["base"] = options.base
        captured["uncommitted_only"] = options.uncommitted_only
        captured["files"] = options.files
        captured["all_files"] = options.all_files
        return []

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def run_analyzers(
        _config: PyslopConfig, _files: list[str], _root: Path
    ) -> AnalyzerRunResult:
        return AnalyzerRunResult()

    def load_rules(_config: PyslopConfig, _repo_root: Path) -> dict[str, RuleMetadata]:
        return {}

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=capture_discovery,
        run_analyzers=run_analyzers,
        load_rules=load_rules,
    )

    run(
        RunOptions(
            repo_root=tmp_path,
            base="origin/main",
            uncommitted_only=True,
            files=("app",),
            all_files=True,
        ),
        deps,
    )

    assert captured == {
        "base": "origin/main",
        "uncommitted_only": True,
        "files": ("app",),
        "all_files": True,
    }


# Why this test survives refactoring: --all still filters findings to the discovered file set.
def test_runner_all_mode_invokes_filename_analyzers_with_discovered_files(
    tmp_path: Path, monkeypatch
) -> None:
    captured_targets: list[list[str]] = []

    def fake_run(
        files: list[str],
        repo_root: Path,
        _config: AnalyzerConfig,
        _executor=None,
    ) -> AnalyzerRunResult:
        captured_targets.append(files)
        return AnalyzerRunResult(
            findings=(
                Finding("app.py", 1, "ruff-PLR0913", "Too many arguments"),
                Finding(str(repo_root / "app.py"), 2, "ruff-C901", "Complex"),
                Finding("outside.py", 3, "ruff-F401", "Unused import"),
            )
        )

    def fake_get_enabled_ruff_only(
        *_args: object, **_kwargs: object
    ) -> list[SimpleNamespace]:
        return [SimpleNamespace(name="ruff")]

    monkeypatch.setattr(
        runner_module,
        "analyzers_for_run",
        fake_get_enabled_ruff_only,
    )
    monkeypatch.setattr(runner_module, "ruff", SimpleNamespace(run=fake_run))

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig(
            disabled_analyzers=frozenset({"pylint", "mypy", "vulture", "complexipy"})
        )

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["app.py"]

    def load_rules(_config: PyslopConfig, _repo_root: Path) -> dict[str, RuleMetadata]:
        return {}

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        load_rules=load_rules,
    )

    result = run(RunOptions(repo_root=tmp_path, all_files=True), deps)

    assert captured_targets == [["app.py"]]
    assert result.findings_count == ALL_MODE_EXPECTED_IN_REPO_FINDINGS


# Why this test survives refactoring: filename analyzers must only receive the discovered path list.
def test_runner_passes_discovered_files_to_filename_analyzers(
    tmp_path: Path, monkeypatch
) -> None:
    # Arrange
    invoked: list[list[str]] = []

    def fake_run(
        files: list[str],
        _repo_root: Path,
        _config: AnalyzerConfig,
        _executor=None,
    ) -> AnalyzerRunResult:
        invoked.append(files)
        return AnalyzerRunResult()

    monkeypatch.setattr(
        runner_module,
        "analyzers_for_run",
        lambda *_args, **_kwargs: [AnalyzerSpec(name="ruff")],
    )
    monkeypatch.setattr(runner_module, "ruff", SimpleNamespace(run=fake_run))

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["app/a.py"]

    def load_rules(_config: PyslopConfig, _repo_root: Path) -> dict[str, RuleMetadata]:
        return {}

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        load_rules=load_rules,
    )

    # Act
    run(RunOptions(repo_root=tmp_path), deps)

    # Assert
    assert invoked == [["app/a.py"]]


# Why this test survives refactoring: CI passes large file lists through one --files-from path.
def test_runner_discovers_paths_from_files_from_list(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
    list_path = tmp_path / "files.txt"
    list_path.write_text("a.py\nb.py\n", encoding="utf-8")
    discovered: list[list[str]] = []

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, options: DiscoveryOptions) -> list[str]:
        discovered.append(list(options.files or ()))
        return list(options.files or ())

    def run_analyzers(
        _config: PyslopConfig, files: list[str], _root: Path
    ) -> AnalyzerRunResult:
        return AnalyzerRunResult()

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        run_analyzers=run_analyzers,
        load_rules=lambda _c, _r: {},
    )

    # Act
    run(
        RunOptions(repo_root=tmp_path, files_from=str(list_path)),
        deps,
    )

    # Assert
    assert discovered == [["a.py", "b.py"]]


# Why this test survives refactoring: timings list only analyzers that actually ran.
def test_runner_records_timings_for_selected_analyzers(
    tmp_path: Path, monkeypatch
) -> None:
    # Arrange
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        runner_module,
        "analyzers_for_run",
        lambda *_args, **_kwargs: [AnalyzerSpec(name="ruff")],
    )
    monkeypatch.setattr(
        runner_module,
        "ruff",
        SimpleNamespace(run=lambda *_a, **_k: AnalyzerRunResult()),
    )

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["app.py"]

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        load_rules=lambda _c, _r: {},
    )

    # Act
    result = run(RunOptions(repo_root=tmp_path, timings=True), deps)

    # Assert
    assert result.timings_text is not None
    assert result.timings_text.startswith("ruff ")
    assert "pylint" not in result.timings_text


# Why this test survives refactoring: the skill rerun loop must skip unchanged filename analyzers.
def test_runner_reuses_filename_cache_until_no_cache(
    tmp_path: Path, monkeypatch
) -> None:
    # Arrange
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    calls: list[int] = []

    def fake_run(*_args: object, **_kwargs: object) -> AnalyzerRunResult:
        calls.append(1)
        return AnalyzerRunResult(
            findings=(Finding("app.py", 1, "ruff-F401", "unused"),)
        )

    monkeypatch.setattr(
        runner_module,
        "analyzers_for_run",
        lambda *_args, **_kwargs: [AnalyzerSpec(name="ruff")],
    )
    monkeypatch.setattr(runner_module, "ruff", SimpleNamespace(run=fake_run))

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["app.py"]

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        load_rules=lambda _c, _r: {},
    )
    options = RunOptions(repo_root=tmp_path)

    # Act
    first = run(options, deps)
    second = run(options, deps)
    forced = run(
        RunOptions(repo_root=tmp_path, no_cache=True),
        deps,
    )

    # Assert
    assert first.findings_count == 1
    assert second.findings_count == 1
    assert forced.findings_count == 1
    assert len(calls) == 2


# Why this test survives refactoring: Windows ruff JSON uses absolute paths; cache must still replay findings.
def test_runner_reuses_filename_cache_when_findings_use_absolute_paths(
    tmp_path: Path, monkeypatch
) -> None:
    # Arrange
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    calls: list[int] = []
    absolute_path = str((tmp_path / "app.py").resolve())

    def fake_run(*_args: object, **_kwargs: object) -> AnalyzerRunResult:
        calls.append(1)
        return AnalyzerRunResult(
            findings=(Finding(absolute_path, 1, "ruff-F401", "unused"),)
        )

    monkeypatch.setattr(
        runner_module,
        "analyzers_for_run",
        lambda *_args, **_kwargs: [AnalyzerSpec(name="ruff")],
    )
    monkeypatch.setattr(runner_module, "ruff", SimpleNamespace(run=fake_run))

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["app.py"]

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        load_rules=lambda _c, _r: {},
    )
    options = RunOptions(repo_root=tmp_path)

    # Act
    first = run(options, deps)
    second = run(options, deps)

    # Assert
    assert first.findings_count == 1
    assert second.findings_count == 1
    assert len(calls) == 1


# Why this test survives refactoring: index analyzers must not run when discovered files miss their roots.
def test_runner_skips_index_analyzer_outside_index_roots(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    calls: list[int] = []

    def fake_run_one(*_args: object, **_kwargs: object) -> AnalyzerRunResult:
        calls.append(1)
        return AnalyzerRunResult()

    monkeypatch.setattr(
        runner_module,
        "analyzers_for_run",
        lambda *_args, **_kwargs: [
            AnalyzerSpec(
                name="lock",
                stage="ci",
                inputs="index",
                index_roots=("pkg/",),
            )
        ],
    )
    monkeypatch.setattr(runner_module, "run_one_extension", fake_run_one)

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["app.py"]

    result = run(
        RunOptions(repo_root=tmp_path, timings=True, stage="ci"),
        RunnerDependencies(
            load_config=load_config,
            discover_files=discover_files,
            load_rules=lambda _c, _r: {},
        ),
    )

    assert calls == []
    assert result.timings_text is None


# Why this test survives refactoring: runner-owned index roots reach the plugin via env.
def test_runner_sets_index_roots_env_for_index_extension(
    tmp_path: Path, monkeypatch
) -> None:
    feature = tmp_path / "pkg" / "mod.py"
    feature.parent.mkdir(parents=True)
    feature.write_text("x = 1\n", encoding="utf-8")
    seen: list[str | None] = []

    def fake_run_one(*_args: object, **_kwargs: object) -> AnalyzerRunResult:
        seen.append(runner_module.environ.get(runner_module.INDEX_ROOTS_ENV))
        return AnalyzerRunResult()

    monkeypatch.setattr(
        runner_module,
        "analyzers_for_run",
        lambda *_args, **_kwargs: [
            AnalyzerSpec(
                name="lock",
                stage="ci",
                inputs="index",
                index_roots=("pkg/",),
            )
        ],
    )
    monkeypatch.setattr(runner_module, "run_one_extension", fake_run_one)

    run(
        RunOptions(
            repo_root=tmp_path,
            files=("pkg/mod.py",),
            stage="ci",
            no_cache=True,
        ),
        RunnerDependencies(
            load_config=lambda _r, _p=None: PyslopConfig(
                extensions=(
                    ExtensionConfig(
                        id="lock",
                        entry_point="ext.py:analyze",
                        stage="ci",
                        inputs="index",
                        index_roots=("pkg/",),
                    ),
                )
            ),
            discover_files=lambda _r, _o: ["pkg/mod.py"],
            load_rules=lambda _c, _r: {},
        ),
    )

    assert seen == ["pkg/"]


# Why this test survives refactoring: packaged regex rule bytes are part of the cache key.
def test_runner_misses_regex_cache_when_rule_pattern_changes(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    calls: list[int] = []

    def fake_regex_run(*_args: object, **_kwargs: object) -> AnalyzerRunResult:
        calls.append(1)
        return AnalyzerRunResult()

    monkeypatch.setattr(
        runner_module,
        "analyzers_for_run",
        lambda *_args, **_kwargs: [AnalyzerSpec(name="regex")],
    )
    monkeypatch.setattr(runner_module, "regex", SimpleNamespace(run=fake_regex_run))

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["app.py"]

    first_rules = {
        "slop-words.todo": RuleMetadata(
            "slop-words.todo", detect_kind="regex", pattern="todo"
        )
    }
    second_rules = {
        "slop-words.todo": RuleMetadata(
            "slop-words.todo", detect_kind="regex", pattern="FIXME"
        )
    }
    rule_sets = iter((first_rules, second_rules))

    def load_rules(_config: PyslopConfig, _repo_root: Path) -> dict[str, RuleMetadata]:
        return next(rule_sets)

    deps = RunnerDependencies(
        load_config=lambda _r, _p=None: PyslopConfig(),
        discover_files=discover_files,
        load_rules=load_rules,
    )
    options = RunOptions(repo_root=tmp_path)
    run(options, deps)
    run(options, deps)

    assert len(calls) == 2


# Why this test survives refactoring: index analyzers may emit extra paths but the report stays on the diff.
def test_runner_filters_index_extension_findings_to_discovered_files(
    tmp_path: Path, monkeypatch
) -> None:
    # Arrange
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")

    def fake_analyzers(*_args: object, **_kwargs: object) -> list[AnalyzerSpec]:
        return [
            AnalyzerSpec(
                name="lock",
                stage="ci",
                inputs="index",
                index_roots=(".",),
            )
        ]

    def fake_run_one(
        _extension: ExtensionConfig,
        _files: list[str],
        _repo_root: Path,
        _executor=None,
    ) -> AnalyzerRunResult:
        return AnalyzerRunResult(
            findings=(
                Finding("app.py", 1, "lock-ap1", "on diff"),
                Finding("other.py", 2, "lock-ap1", "outside diff"),
            )
        )

    monkeypatch.setattr(runner_module, "analyzers_for_run", fake_analyzers)
    monkeypatch.setattr(runner_module, "run_one_extension", fake_run_one)

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig(
            extensions=(
                ExtensionConfig(
                    id="lock",
                    entry_point="ext.py:analyze",
                    stage="ci",
                    inputs="index",
                    index_roots=(".",),
                ),
            )
        )

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["app.py"]

    def load_rules(_config: PyslopConfig, _repo_root: Path) -> dict[str, RuleMetadata]:
        return {}

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        load_rules=load_rules,
    )

    # Act
    result = run(RunOptions(repo_root=tmp_path, stage="ci"), deps)

    # Assert
    assert result.findings_count == 1
    assert result.stdout_text is not None
    assert "app.py" in result.stdout_text
    assert "other.py" not in result.stdout_text


# Why this test survives refactoring: one pyslop process invokes each analyzer once with the full file list.
def test_runner_invokes_file_scoped_analyzer_once_for_large_target_list(
    tmp_path: Path, monkeypatch
) -> None:
    files = ["a" * 40 + ".py", "b" * 40 + ".py", "c" * 40 + ".py"]
    ruff_targets: list[list[str]] = []

    def fake_ruff_run(
        batch: list[str],
        _repo_root: Path,
        _config: AnalyzerConfig,
        _executor=None,
    ) -> AnalyzerRunResult:
        ruff_targets.append(batch)
        return AnalyzerRunResult(
            findings=(Finding(batch[0], 1, "ruff-F401", "unused"),)
        )

    def fake_get_enabled_ruff_only(
        *_args: object, **_kwargs: object
    ) -> list[SimpleNamespace]:
        return [SimpleNamespace(name="ruff")]

    monkeypatch.setattr(
        runner_module,
        "analyzers_for_run",
        fake_get_enabled_ruff_only,
    )
    monkeypatch.setattr(runner_module, "ruff", SimpleNamespace(run=fake_ruff_run))

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig(
            disabled_analyzers=frozenset({"pylint", "mypy", "vulture", "complexipy"})
        )

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return files

    def load_rules(_config: PyslopConfig, _repo_root: Path) -> dict[str, RuleMetadata]:
        return {}

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        load_rules=load_rules,
    )

    result = run(RunOptions(repo_root=tmp_path), deps)

    assert result.findings_count == 1
    assert ruff_targets == [files]


# Why this test survives refactoring: detect-secrets needs explicit files in all-files mode.
def test_runner_uses_discovered_files_for_detect_secrets_when_all_files_enabled(
    tmp_path: Path, monkeypatch
) -> None:
    files = ["app/a.py", "app/credentials.yaml"]
    captured_targets: list[list[str]] = []

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return files

    def fake_get_enabled_detect_secrets_only(
        *_args: object,
        **_kwargs: object,
    ) -> list[SimpleNamespace]:
        return [SimpleNamespace(name="detect-secrets")]

    def fake_detect_secrets_run(
        batch: list[str],
        _repo_root: Path,
        _config: AnalyzerConfig,
        _executor=None,
    ) -> AnalyzerRunResult:
        captured_targets.append(batch)
        return AnalyzerRunResult()

    monkeypatch.setattr(
        runner_module,
        "analyzers_for_run",
        fake_get_enabled_detect_secrets_only,
    )
    monkeypatch.setattr(
        runner_module,
        "detect_secrets",
        SimpleNamespace(run=fake_detect_secrets_run),
    )

    deps = RunnerDependencies(load_config=load_config, discover_files=discover_files)

    run(RunOptions(repo_root=tmp_path, all_files=True), deps)

    assert captured_targets == [files]


# Why this test survives refactoring: builtin analyzer findings must flow into AXI stdout.
def test_runner_routes_detect_secrets_findings_into_stdout(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "config.yaml").write_text("secret: value\n", encoding="utf-8")

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["config.yaml"]

    def fake_get_enabled_detect_secrets_only(
        *_args: object,
        **_kwargs: object,
    ) -> list[SimpleNamespace]:
        return [SimpleNamespace(name="detect-secrets")]

    def fake_detect_secrets_run(
        _files: list[str],
        _repo_root: Path,
        _config: AnalyzerConfig,
        _executor=None,
    ) -> AnalyzerRunResult:
        return AnalyzerRunResult(
            findings=(Finding("config.yaml", 3, "secrets", "Private Key detected"),)
        )

    def load_rules(_config: PyslopConfig, _repo_root: Path) -> dict[str, RuleMetadata]:
        return {}

    monkeypatch.setattr(
        runner_module,
        "analyzers_for_run",
        fake_get_enabled_detect_secrets_only,
    )
    monkeypatch.setattr(
        runner_module,
        "detect_secrets",
        SimpleNamespace(run=fake_detect_secrets_run),
        raising=False,
    )
    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        load_rules=load_rules,
    )

    result = run(RunOptions(repo_root=tmp_path, full=True), deps)

    report = result.stdout_text or ""
    assert result.findings_count == 1
    assert "config.yaml" in report
    assert "Private Key detected" in report


# Why this test survives refactoring: bundled rule metadata is loaded through the runner boundary.
def test_runner_renders_bundled_detect_secrets_rule_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "config.yaml").write_text("secret: value\n", encoding="utf-8")
    rules_path = tmp_path / ".pyslop" / "analyzers" / "detect_secrets" / "rules.toml"
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(
        """
[rules.secrets]
name = "Hardcoded secret"
fix = "Replace the hardcoded secret with an environment variable or secrets manager reference."
""",
        encoding="utf-8",
    )

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig(
            analyzer_configs={
                "detect-secrets": AnalyzerConfig(
                    rules=".pyslop/analyzers/detect_secrets/rules.toml"
                )
            }
        )

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["config.yaml"]

    def fake_get_enabled_detect_secrets_only(
        *_args: object,
        **_kwargs: object,
    ) -> list[SimpleNamespace]:
        return [SimpleNamespace(name="detect-secrets")]

    def fake_detect_secrets_run(
        _files: list[str],
        _repo_root: Path,
        _config: AnalyzerConfig,
        _executor=None,
    ) -> AnalyzerRunResult:
        return AnalyzerRunResult(
            findings=(Finding("config.yaml", 3, "secrets", "Private Key detected"),)
        )

    monkeypatch.setattr(
        runner_module,
        "analyzers_for_run",
        fake_get_enabled_detect_secrets_only,
    )
    monkeypatch.setattr(
        runner_module,
        "detect_secrets",
        SimpleNamespace(run=fake_detect_secrets_run),
    )
    deps = RunnerDependencies(load_config=load_config, discover_files=discover_files)

    result = run(RunOptions(repo_root=tmp_path), deps)

    report = result.stdout_text or ""
    assert (
        "Replace the hardcoded secret with an environment variable or secrets manager reference."
        in report
    )


# Why this test survives refactoring: extension rule metadata is verified through AXI stdout.
def test_runner_renders_registered_extension_rule_metadata(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "app.py").write_text("# issue\n", encoding="utf-8")
    rules_path = tmp_path / "rules" / "custom.toml"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text(
        """
[rules.custom-rule]
name = "Custom Rule"
fix = "Fix from extension metadata."
""",
        encoding="utf-8",
    )

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig(
            extensions=(
                ExtensionConfig(
                    id="custom",
                    command=("python", "audit.py"),
                    rules="rules/custom.toml",
                ),
            )
        )

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["app.py"]

    def run_analyzers(
        _config: PyslopConfig, _files: list[str], _root: Path
    ) -> AnalyzerRunResult:
        return AnalyzerRunResult(
            findings=(Finding("app.py", 1, "custom-rule", "Issue"),)
        )

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        run_analyzers=run_analyzers,
    )

    # Act
    result = run(RunOptions(repo_root=tmp_path), deps)

    # Assert
    report = result.stdout_text or ""
    assert result.findings_count == 1
    assert "custom-rule" in report
    assert "Fix from extension metadata." in report


# Why this test survives refactoring: analyzer rule metadata source is the configured workspace path.
def test_load_analyzer_rules_reads_from_configured_workspace_paths(
    tmp_path: Path,
) -> None:
    rules_path = tmp_path / ".pyslop" / "analyzers" / "ruff" / "rules.toml"
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(
        """
[rules.ruff-F401]
name = "unused-import"
fix = "Remove unused imports."
""",
        encoding="utf-8",
    )

    rules = load_rules(
        PyslopConfig(
            analyzer_configs={
                "ruff": AnalyzerConfig(rules=".pyslop/analyzers/ruff/rules.toml")
            }
        ),
        tmp_path,
    )

    assert "ruff-F401" in rules
    assert rules["ruff-F401"].name == "unused-import"
    assert rules["ruff-F401"].fix == "Remove unused imports."


# Why this test survives refactoring: configured analyzer rules paths are a strict runtime contract.
def test_load_analyzer_rules_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RulesError) as excinfo:
        load_rules(
            PyslopConfig(
                analyzer_configs={
                    "ruff": AnalyzerConfig(rules=".pyslop/analyzers/ruff/rules.toml")
                }
            ),
            tmp_path,
        )
    assert ".pyslop/analyzers/ruff/rules.toml" in str(excinfo.value)


# Why this test survives refactoring: no configured rules should produce empty metadata.
def test_load_rules_returns_empty_when_no_rules_configured(tmp_path: Path) -> None:
    rules = load_rules(PyslopConfig(), tmp_path)
    assert "slop-words.todo" in rules
    assert rules["slop-words.todo"].detect_kind == "regex"


# Why this test survives refactoring: inline config rules are explicit user overrides.
def test_load_rules_inline_overrides_win_over_analyzer_rules(tmp_path: Path) -> None:
    rules_path = tmp_path / ".pyslop" / "analyzers" / "ruff" / "rules.toml"
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(
        """
[rules.ruff-F401]
name = "workspace name"
fix = "workspace fix"
""",
        encoding="utf-8",
    )

    rules = load_rules(
        PyslopConfig(
            analyzer_configs={
                "ruff": AnalyzerConfig(rules=".pyslop/analyzers/ruff/rules.toml")
            },
            rules={
                "ruff-F401": RuleMetadata("ruff-F401", "inline name", "inline fix", ())
            },
        ),
        tmp_path,
    )

    assert rules["ruff-F401"].name == "inline name"
    assert rules["ruff-F401"].fix == "inline fix"


# Why this test survives refactoring: existing builtins receive the public discovered target set.
def test_runner_passes_non_python_targets_to_existing_builtins(
    tmp_path: Path, monkeypatch
) -> None:
    files = ["app/main.py", "config.yaml"]
    ruff_targets: list[list[str]] = []
    mypy_targets: list[list[str]] = []

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return files

    def fake_get_enabled_existing_analyzers(
        *_args: object,
        **_kwargs: object,
    ) -> list[SimpleNamespace]:
        return [SimpleNamespace(name="ruff"), SimpleNamespace(name="mypy")]

    def fake_ruff_run(
        targets: list[str],
        _repo_root: Path,
        _config: AnalyzerConfig,
        _executor=None,
    ) -> AnalyzerRunResult:
        ruff_targets.append(targets)
        return AnalyzerRunResult()

    def fake_mypy_run(
        targets: list[str],
        _repo_root: Path,
        _config: AnalyzerConfig,
        _executor=None,
    ) -> AnalyzerRunResult:
        mypy_targets.append(targets)
        return AnalyzerRunResult()

    monkeypatch.setattr(
        runner_module,
        "analyzers_for_run",
        fake_get_enabled_existing_analyzers,
    )
    monkeypatch.setattr(runner_module, "ruff", SimpleNamespace(run=fake_ruff_run))
    monkeypatch.setattr(runner_module, "mypy", SimpleNamespace(run=fake_mypy_run))
    deps = RunnerDependencies(load_config=load_config, discover_files=discover_files)

    result = run(RunOptions(repo_root=tmp_path), deps)

    assert ruff_targets == [files]
    assert mypy_targets == [files]
    assert result.errors == ()


# Why this test survives refactoring: the shared disable list is observed through the public run result.
def test_runner_skips_disabled_builtin_and_extension_analyzers(
    tmp_path: Path, monkeypatch
) -> None:
    # Arrange
    (tmp_path / "app.py").write_text("print('x')\n", encoding="utf-8")

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig(
            disabled_analyzers=frozenset({"ruff", "custom-entry"}),
            extensions=(
                ExtensionConfig(
                    id="custom-entry",
                    entry_point="tests.test_runner_scaffold_cli:runner_entry_extension",
                ),
            ),
        )

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["app.py"]

    def fake_get_enabled_ruff_only(
        *_args: object, **_kwargs: object
    ) -> list[SimpleNamespace]:
        return []

    def fake_ruff_run(
        _files: list[str],
        _repo_root: Path,
        _config: AnalyzerConfig,
        _executor=None,
    ) -> AnalyzerRunResult:
        return AnalyzerRunResult(
            findings=(Finding("app.py", 1, "ruff-F401", "Unused import"),)
        )

    monkeypatch.setattr(
        runner_module,
        "analyzers_for_run",
        fake_get_enabled_ruff_only,
    )
    monkeypatch.setattr(runner_module, "ruff", SimpleNamespace(run=fake_ruff_run))
    deps = RunnerDependencies(load_config=load_config, discover_files=discover_files)

    # Act
    result = run(RunOptions(repo_root=tmp_path), deps)

    # Assert
    assert result.exit_code == 0
    assert result.findings_count == 0
    assert result.errors == ()


# Why this test survives refactoring: detect-secrets uses the same batching contract as builtins.
def test_runner_batches_large_target_lists_for_detect_secrets(
    tmp_path: Path, monkeypatch
) -> None:
    files = ["a" * 40 + ".yaml", "b" * 40 + ".yaml", "c" * 40 + ".yaml"]
    detect_secrets_targets: list[list[str]] = []

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return files

    def fake_get_enabled_detect_secrets_only(
        *_args: object,
        **_kwargs: object,
    ) -> list[SimpleNamespace]:
        return [SimpleNamespace(name="detect-secrets")]

    def fake_detect_secrets_run(
        batch: list[str],
        _repo_root: Path,
        _config: AnalyzerConfig,
        _executor=None,
    ) -> AnalyzerRunResult:
        detect_secrets_targets.append(batch)
        return AnalyzerRunResult()

    monkeypatch.setattr(
        runner_module,
        "analyzers_for_run",
        fake_get_enabled_detect_secrets_only,
    )
    monkeypatch.setattr(
        runner_module,
        "detect_secrets",
        SimpleNamespace(run=fake_detect_secrets_run),
    )
    deps = RunnerDependencies(load_config=load_config, discover_files=discover_files)

    result = run(RunOptions(repo_root=tmp_path), deps)

    assert detect_secrets_targets == [files]
    assert result.errors == ()


# Why this test survives refactoring: analyzer path normalization must preserve findings even when tools emit basename-only paths.
def test_runner_maps_unique_basename_findings_to_discovered_file_path(
    tmp_path: Path, monkeypatch
) -> None:
    # Arrange
    target = tmp_path / "pyslop" / "pyslop" / "cli.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def main():\n    return 0\n", encoding="utf-8")

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["pyslop/pyslop/cli.py"]

    def fake_complexipy_run(
        _files: list[str],
        _repo_root: Path,
        _config: AnalyzerConfig,
        _executor=None,
    ) -> AnalyzerRunResult:
        return AnalyzerRunResult(
            findings=(Finding("cli.py", 1, "complexipy", "complexity too high"),)
        )

    def load_rules(_config: PyslopConfig, _repo_root: Path) -> dict[str, RuleMetadata]:
        return {}

    def fake_get_enabled_complexipy_only(
        *_args: object,
        **_kwargs: object,
    ) -> list[SimpleNamespace]:
        return [SimpleNamespace(name="complexipy")]

    monkeypatch.setattr(
        runner_module,
        "analyzers_for_run",
        fake_get_enabled_complexipy_only,
    )
    monkeypatch.setattr(
        runner_module,
        "complexipy",
        SimpleNamespace(run=fake_complexipy_run),
    )

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        load_rules=load_rules,
    )

    # Act
    result = run(RunOptions(repo_root=tmp_path), deps)

    # Assert
    report = result.stdout_text or ""
    assert result.findings_count == 1
    assert result.files_with_findings_count == 1
    assert "pyslop/pyslop/cli.py" in report


# Why this test survives refactoring: ambiguous basename-only paths should not be guessed to the wrong discovered file.
def test_runner_ignores_basename_finding_when_multiple_discovered_files_match(
    tmp_path: Path, monkeypatch
) -> None:
    # Arrange
    app_one = tmp_path / "app" / "one" / "cli.py"
    app_two = tmp_path / "app" / "two" / "cli.py"
    app_one.parent.mkdir(parents=True, exist_ok=True)
    app_two.parent.mkdir(parents=True, exist_ok=True)
    app_one.write_text("def one():\n    return 1\n", encoding="utf-8")
    app_two.write_text("def two():\n    return 2\n", encoding="utf-8")

    def load_config(_root: Path, _path: str | None = None) -> PyslopConfig:
        return PyslopConfig()

    def discover_files(_root: Path, _options: DiscoveryOptions) -> list[str]:
        return ["app/one/cli.py", "app/two/cli.py"]

    def fake_complexipy_run(
        _files: list[str],
        _repo_root: Path,
        _config: AnalyzerConfig,
        _executor=None,
    ) -> AnalyzerRunResult:
        return AnalyzerRunResult(
            findings=(Finding("cli.py", 1, "complexipy", "complexity too high"),)
        )

    def load_rules(_config: PyslopConfig, _repo_root: Path) -> dict[str, RuleMetadata]:
        return {}

    def fake_get_enabled_complexipy_only(
        *_args: object,
        **_kwargs: object,
    ) -> list[SimpleNamespace]:
        return [SimpleNamespace(name="complexipy")]

    monkeypatch.setattr(
        runner_module,
        "analyzers_for_run",
        fake_get_enabled_complexipy_only,
    )
    monkeypatch.setattr(
        runner_module,
        "complexipy",
        SimpleNamespace(run=fake_complexipy_run),
    )

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        load_rules=load_rules,
    )

    # Act
    result = run(RunOptions(repo_root=tmp_path), deps)

    # Assert
    assert result.findings_count == 0
    assert result.files_with_findings_count == 0


# Why this test survives refactoring: default-stage inspect omits CI-only pylint.
def test_inspect_analyzers_omits_pylint_on_default_stage(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    deps = RunnerDependencies(
        load_config=lambda _root, _path=None: PyslopConfig(),
        discover_files=lambda _root, _options: ["app.py"],
        load_rules=lambda _config, _root: {},
    )
    result = inspect_analyzers(
        RunOptions(repo_root=tmp_path, files=("app.py",)),
        deps,
    )
    assert result.exit_code == 0
    assert result.stdout_text is not None
    assert (
        "pylint"
        not in result.stdout_text.split("analyzers[", 1)[1].split("skipped[", 1)[0]
    )


# Why this test survives refactoring: packaged configs belong in the cache dir, not process temp.
def test_packaged_analyzer_config_does_not_grow_process_temps(tmp_path: Path) -> None:
    tempdir = Path(tempfile.gettempdir())
    before = {path.name for path in tempdir.glob("pyslop-*")}
    packaged_analyzer_config("ruff", tmp_path)
    packaged_analyzer_config("ruff", tmp_path)
    after = {path.name for path in tempdir.glob("pyslop-*")}
    assert after == before
    packaged_dir = tmp_path / ".pyslop" / "cache" / "packaged"
    assert packaged_dir.is_dir()
    assert any(packaged_dir.iterdir())


def runner_entry_extension(
    files: list[str], repo_root: Path, config_path: str | None
) -> list[Finding]:
    return [Finding(files[0], 1, "custom-entry", "Entry issue")]
