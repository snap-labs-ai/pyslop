from pathlib import Path
from types import SimpleNamespace

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


# Why this test survives refactoring: it observes the runner's public report and exit-code contract.
def test_cli_init_prints_created_files(tmp_path: Path, capsys, monkeypatch) -> None:
    created = (
        tmp_path / ".agents" / "skills" / "pyslop" / "SKILL.md",
        tmp_path / "pyslop.toml",
    )
    monkeypatch.chdir(tmp_path)

    def stub_scaffold(
        _repo_root: Path,
        _target: str | None = None,
        overwrite: bool = False,
    ) -> ScaffoldResult:
        _ = overwrite
        return ScaffoldResult(created=created)

    monkeypatch.setattr("pyslop.cli.scaffold", stub_scaffold)

    result = main(["init"])

    captured = capsys.readouterr()
    assert result == 0
    assert "pyslop: init completed. Created 2 files:" in captured.out
    assert "- .agents/skills/pyslop/SKILL.md" in captured.out
    assert "- pyslop.toml" in captured.out


# Why this test survives refactoring: extensions command should install templates in existing init setup.
def test_cli_extensions_standalone_installs_templates(
    tmp_path: Path, monkeypatch
) -> None:
    scaffold(tmp_path, "cursor")
    monkeypatch.chdir(tmp_path)

    result = main(["extensions"])

    assert result == 0
    assert not (tmp_path / "pyslop_extensions" / "slop_words").exists()
    assert (tmp_path / "pyslop_extensions" / "detect_shims" / "analyzer.py").exists()


# Why this test survives refactoring: extensions command without init should fail with clear user guidance.
def test_cli_extensions_standalone_errors_without_pyslop_toml(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    result = main(["extensions"])

    captured = capsys.readouterr()
    assert result == ERROR_EXIT_CODE
    assert "pyslop.toml not found. Run pyslop init first." in captured.out


# Why this test survives refactoring: init and extensions can be combined in one command.
def test_cli_init_with_extensions_runs_both(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = main(["init", "--extensions", "detect-shims"])

    config = (tmp_path / "pyslop.toml").read_text(encoding="utf-8")
    assert result == 0
    assert not (tmp_path / ".pyslop" / "analyzers").exists()
    assert (tmp_path / "pyslop_extensions" / "detect_shims" / "analyzer.py").exists()
    assert 'id = "detect-shims"' in config


# Why this test survives refactoring: clean runs print AXI empty state on stdout.
def test_cli_prints_axi_empty_state(tmp_path: Path, capsys, monkeypatch) -> None:
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
    monkeypatch.chdir(tmp_path)

    def cli_run(opts: RunOptions) -> RunResult:
        return run(opts, deps)

    monkeypatch.setattr("pyslop.cli.run", cli_run)
    result = main(["run"])

    captured = capsys.readouterr()
    assert result == 0
    assert "findings: 0 in this file set" in captured.out


# Why this test survives refactoring: findings print AXI tables and exit 0 without --strict.
def test_cli_prints_axi_findings_exit_zero(tmp_path: Path, capsys, monkeypatch) -> None:
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
        return {}

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        run_analyzers=run_analyzers,
        load_rules=load_rules,
    )
    monkeypatch.chdir(tmp_path)

    def cli_run(opts: RunOptions) -> RunResult:
        return run(opts, deps)

    monkeypatch.setattr("pyslop.cli.run", cli_run)
    result = main(["run"])

    captured = capsys.readouterr()
    assert result == 0
    assert "findings[1]{path,line,rule,fix,message}:" in captured.out
    assert "app.py,1,custom" in captured.out


# Why this test survives refactoring: --strict maps findings to exit 1.
def test_cli_strict_exits_one_on_findings(tmp_path: Path, capsys, monkeypatch) -> None:
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
        return {}

    deps = RunnerDependencies(
        load_config=load_config,
        discover_files=discover_files,
        run_analyzers=run_analyzers,
        load_rules=load_rules,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pyslop.cli.run", lambda opts: run(opts, deps))
    result = main(["run", "--strict"])
    assert result == 1
    assert "findings[1]" in capsys.readouterr().out


# Why this test survives refactoring: users rely on --files forwarding multiple explicit paths.
def test_cli_forwards_multiple_explicit_files(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, tuple[str, ...] | bool | None] = {}

    def capture_run(opts: RunOptions) -> RunResult:
        captured["files"] = opts.files
        captured["strict"] = opts.strict
        return RunResult(
            exit_code=0, findings_count=0, stdout_text="findings: 0 in this file set\n"
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pyslop.cli.run", capture_run)

    result = main(["run", "--files", "app/a.py", "--files", "backend/b.py"])

    assert result == 0
    assert captured == {
        "files": ("app/a.py", "backend/b.py"),
        "strict": False,
    }


# Why this test survives refactoring: analyzer errors go to stdout as AXI errors.
def test_cli_prints_structured_errors_on_stdout(
    tmp_path: Path, capsys, monkeypatch
) -> None:
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
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pyslop.cli.run", lambda opts: run(opts, deps))
    result = main(["run"])
    captured = capsys.readouterr()
    assert result == ERROR_EXIT_CODE
    assert "error: bad config" in captured.out
    assert captured.err == ""


# Why this test survives refactoring: unknown flags fail loud on stdout.
def test_cli_rejects_unknown_flag_on_stdout(capsys) -> None:
    result = main(["run", "--stat"])
    captured = capsys.readouterr()
    assert result == ERROR_EXIT_CODE
    assert "error:" in captured.out
    assert "--stat" in captured.out
    assert "pyslop run --help" in captured.out


# Why this test survives refactoring: help documents --strict and --full.
def test_cli_help_documents_strict_and_full(capsys) -> None:
    result = main(["run", "--help"])
    captured = capsys.readouterr()
    assert result == 0
    assert "--strict" in captured.out
    assert "--full" in captured.out
    assert "--files" in captured.out
    assert "--stage" in captured.out
    assert "--fields" in captured.out


# Why this test survives refactoring: bare pyslop without a subcommand still runs analysis.
def test_cli_bare_invocation_runs_analysis(tmp_path: Path, monkeypatch) -> None:
    seen: list[str] = []

    def capture_run(opts: RunOptions) -> RunResult:
        seen.append("ran")
        return RunResult(
            exit_code=0, findings_count=0, stdout_text="findings: 0 in this file set\n"
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pyslop.cli.run", capture_run)
    result = main([])
    assert result == 0
    assert seen == ["ran"]


# Why this test survives refactoring: --help must not start analyzers.
def test_cli_help_does_not_run_analysis(monkeypatch, capsys) -> None:
    def boom(_opts: RunOptions) -> RunResult:
        raise AssertionError("analysis should not run")

    monkeypatch.setattr("pyslop.cli.run", boom)
    result = main(["--help"])
    assert result == 0
    assert "Usage:" in capsys.readouterr().out


# Why this test survives refactoring: git-less dirs must not look like a clean findings run.
def test_cli_git_discovery_errors_outside_work_tree(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    result = main(["run"])
    captured = capsys.readouterr()
    assert result == ERROR_EXIT_CODE
    assert "error:" in captured.out
    assert "git discovery" in captured.out


# Why this test survives refactoring: unknown --fields names are a usage error, not analysis.
def test_cli_rejects_unknown_fields(capsys) -> None:
    result = main(["run", "--fields", "path,nope"])
    captured = capsys.readouterr()
    assert result == ERROR_EXIT_CODE
    assert "unknown finding field: nope" in captured.out


# Why this test survives refactoring: pyslop analyzers lists tools without starting run().
def test_cli_analyzers_accepts_files_without_running_analysis(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    seen: list[tuple[str, ...]] = []

    def capture_inspect(opts: RunOptions) -> RunResult:
        seen.append(opts.files or ())
        return RunResult(
            exit_code=0,
            findings_count=0,
            stdout_text="analyzers[1]:\n  ruff\n",
        )

    def boom(_opts: RunOptions) -> RunResult:
        raise AssertionError("analysis should not run")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pyslop.cli.inspect_analyzers", capture_inspect)
    monkeypatch.setattr("pyslop.cli.run", boom)
    result = main(["analyzers", "--files", "app.py"])
    assert result == 0
    assert seen == [("app.py",)]
    assert "ruff" in capsys.readouterr().out


# Why this test survives refactoring: --stage only accepts the documented ci value.
def test_cli_rejects_invalid_stage(capsys) -> None:
    result = main(["run", "--stage", "pre-commit", "--files", "app.py"])
    captured = capsys.readouterr()
    assert result == ERROR_EXIT_CODE
    assert "error:" in captured.out
    assert "help:" in captured.out

