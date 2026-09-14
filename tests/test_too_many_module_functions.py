from pathlib import Path

from pyslop.analyzers.too_many_module_functions import (
    DEFAULT_MAX_MODULE_FUNCTIONS,
    run,
)
from pyslop.runner import run as run_repo
from pyslop.scaffold import scaffold
from pyslop.types import AnalyzerConfig, Finding, RunOptions


def _write_functions(path: Path, names: list[str]) -> None:
    body = "\n\n".join(f"def {name}() -> None:\n    return None" for name in names)
    path.write_text(body + "\n", encoding="utf-8")


# Why this test survives refactoring: ten public module functions is the packaged default cap.
def test_run_allows_ten_public_module_functions(tmp_path: Path) -> None:
    names = [f"fn_{index}" for index in range(DEFAULT_MAX_MODULE_FUNCTIONS)]
    _write_functions(tmp_path / "app.py", names)

    result = run(["app.py"], tmp_path, AnalyzerConfig())

    assert result.findings == ()


# Why this test survives refactoring: the eleventh public def is the public overflow finding.
def test_run_reports_eleventh_public_module_function(tmp_path: Path) -> None:
    names = [f"fn_{index}" for index in range(DEFAULT_MAX_MODULE_FUNCTIONS + 1)]
    _write_functions(tmp_path / "app.py", names)

    result = run(["app.py"], tmp_path, AnalyzerConfig())

    assert result.findings == (
        Finding(
            "app.py",
            31,
            "too-many-module-functions",
            "Too many public module-level functions (11 > 10)",
        ),
    )


# Why this test survives refactoring: private names and class methods are not the module surface.
def test_run_ignores_private_and_method_defs(tmp_path: Path) -> None:
    public_rest = "\n".join(
        f"def public_{index}() -> None:\n    return None\n" for index in range(9)
    )
    (tmp_path / "app.py").write_text(
        "def public_one() -> None:\n    return None\n\n"
        "def _hidden() -> None:\n    return None\n\n"
        "class Holder:\n"
        "    def method_a(self) -> None:\n        return None\n"
        "    def method_b(self) -> None:\n        return None\n\n"
        f"{public_rest}",
        encoding="utf-8",
    )

    result = run(["app.py"], tmp_path, AnalyzerConfig())

    assert result.findings == ()


# Why this test survives refactoring: nested defs are not module-level.
def test_run_ignores_nested_functions(tmp_path: Path) -> None:
    names = [f"fn_{index}" for index in range(DEFAULT_MAX_MODULE_FUNCTIONS)]
    nested = (
        "def outer() -> None:\n"
        "    def inner() -> None:\n"
        "        return None\n"
        "    return None\n\n"
    )
    rest = "\n\n".join(f"def {name}() -> None:\n    return None" for name in names[1:])
    (tmp_path / "app.py").write_text(nested + rest + "\n", encoding="utf-8")

    result = run(["app.py"], tmp_path, AnalyzerConfig())

    assert result.findings == ()


# Why this test survives refactoring: async module functions count toward the public surface.
def test_run_counts_async_module_functions(tmp_path: Path) -> None:
    lines = [
        f"async def fn_{index}() -> None:\n    return None\n"
        for index in range(DEFAULT_MAX_MODULE_FUNCTIONS + 1)
    ]
    (tmp_path / "app.py").write_text("\n".join(lines), encoding="utf-8")

    result = run(["app.py"], tmp_path, AnalyzerConfig())

    assert len(result.findings) == 1
    assert result.findings[0].rule_id == "too-many-module-functions"
    assert "(11 > 10)" in result.findings[0].message


# Why this test survives refactoring: packaged config overlay changes the cap.
def test_run_honors_max_module_functions_config(tmp_path: Path) -> None:
    config_path = tmp_path / "cap.toml"
    config_path.write_text("max-module-functions = 2\n", encoding="utf-8")
    _write_functions(tmp_path / "app.py", ["one", "two", "three"])

    result = run(
        ["app.py"],
        tmp_path,
        AnalyzerConfig(config=str(config_path)),
    )

    assert result.findings[0].message == (
        "Too many public module-level functions (3 > 2)"
    )


# Why this test survives refactoring: unreadable Python is skipped, not a tool error.
def test_run_skips_syntax_error_files(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def broken(\n", encoding="utf-8")

    result = run(["app.py"], tmp_path, AnalyzerConfig())

    assert result.findings == ()
    assert result.errors == ()


# Why this test survives refactoring: the builtin is on the default run without a host extension.
def test_runner_emits_rule_fix_from_packaged_metadata(tmp_path: Path) -> None:
    scaffold(tmp_path)
    names = [f"fn_{index}" for index in range(DEFAULT_MAX_MODULE_FUNCTIONS + 1)]
    _write_functions(tmp_path / "app.py", names)
    config = tmp_path / "pyslop.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "disable = []",
            'disable = ["ruff", "pylint", "mypy", "vulture", "complexipy", "detect-secrets"]',
        ),
        encoding="utf-8",
    )

    result = run_repo(RunOptions(repo_root=tmp_path, files=("app.py",)))

    assert result.findings_count == 1
    assert result.stdout_text is not None
    assert "too-many-module-functions" in result.stdout_text
    assert "Split the module along existing seams" in result.stdout_text
