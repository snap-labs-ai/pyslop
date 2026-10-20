from __future__ import annotations

import sys
from pathlib import Path

from pyslop.analyzers.import_boundaries import run as analyze
from pyslop.analyzers.import_boundaries.discover import discover_root_packages
from pyslop.analyzers.registry import BUILTIN_ANALYZERS
from pyslop.runner import run
from pyslop.types import AnalyzerConfig, Finding, RunOptions


def write(root: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not text.endswith("\n"):
            text = text + "\n"
        path.write_text(text, encoding="utf-8")


def python_files(root: Path) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def analyze_tree(
    root: Path, files: list[str] | None = None
) -> tuple[Finding, ...]:
    selected = python_files(root) if files is None else files
    result = analyze(selected, root, AnalyzerConfig())
    assert result.errors == (), result.errors
    return result.findings


def rule_ids(found: tuple[Finding, ...]) -> set[str]:
    return {item.rule_id for item in found}


# Why this test survives refactoring: package discovery is the contract input.
def test_discover_root_packages_includes_src_and_test_roots(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "tests/__init__.py": "",
            "src/lib/__init__.py": "",
            ".hidden/nope/__init__.py": "",
            "src/.secret/nope/__init__.py": "",
            "loose.py": "x = 1",
        },
    )

    packages = discover_root_packages(tmp_path)

    assert {(item.name, item.is_test) for item in packages} == {
        ("app", False),
        ("tests", True),
        ("lib", False),
    }


# Why this test survives refactoring: a tree without a package must not fail the run.
def test_loose_scripts_restore_sys_path_and_skip_non_python(tmp_path: Path) -> None:
    write(tmp_path, {"loose.py": "x = 1", "notes.md": "hello"})
    before = list(sys.path)

    result = analyze(["loose.py", "notes.md"], tmp_path, AnalyzerConfig())
    markdown_only = analyze(["notes.md"], tmp_path, AnalyzerConfig())

    assert result.findings == ()
    assert result.errors == ()
    assert markdown_only.findings == ()
    assert sys.path == before


# Why this test survives refactoring: typing-only imports are not architecture edges.
def test_type_checking_cycle_is_ignored(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/left.py": (
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n"
                "    from app.right import VALUE\n"
                "VALUE = 1"
            ),
            "app/right.py": (
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n"
                "    from app.left import VALUE\n"
                "VALUE = 2"
            ),
        },
    )

    assert "import-boundaries.acyclic-siblings" not in rule_ids(analyze_tree(tmp_path))


# Why this test survives refactoring: cycles between child packages are reported.
def test_child_cycle_is_reported(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/blue/__init__.py": "",
            "app/blue/deep.py": "from app.green.deep import VALUE\nVALUE = 1",
            "app/green/__init__.py": "",
            "app/green/deep.py": "from app.blue.deep import VALUE\nVALUE = 2",
        },
    )

    found = analyze_tree(tmp_path)

    assert any(
        item.rule_id == "import-boundaries.acyclic-siblings"
        and item.path == "app/blue/deep.py"
        for item in found
    )


# Why this test survives refactoring: cycles between grandchildren are reported.
def test_grandchild_cycle_is_reported(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/feature/__init__.py": "",
            "app/feature/left.py": "from app.feature.right import VALUE\nVALUE = 1",
            "app/feature/right.py": "from app.feature.left import VALUE\nVALUE = 2",
        },
    )

    assert "import-boundaries.acyclic-siblings" in rule_ids(analyze_tree(tmp_path))


# Why this test survives refactoring: deeper sibling sets are outside the default depth.
def test_deeper_cycle_is_ignored(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/feature/__init__.py": "",
            "app/feature/area/__init__.py": "",
            "app/feature/area/left.py": "from app.feature.area.right import VALUE\nVALUE = 1",
            "app/feature/area/right.py": "from app.feature.area.left import VALUE\nVALUE = 2",
        },
    )

    assert "import-boundaries.acyclic-siblings" not in rule_ids(analyze_tree(tmp_path))


# Why this test survives refactoring: generated trees are not checked as sibling sets.
def test_migrations_cycle_is_ignored(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/migrations/__init__.py": "",
            "app/migrations/a.py": "from app.migrations.b import VALUE\nVALUE = 1",
            "app/migrations/b.py": "from app.migrations.a import VALUE\nVALUE = 2",
        },
    )

    assert "import-boundaries.acyclic-siblings" not in rule_ids(analyze_tree(tmp_path))


# Why this test survives refactoring: feature siblings may not depend on each other.
def test_cross_feature_import_is_independent_violation(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/features/__init__.py": "",
            "app/features/billing/__init__.py": "from app.features.users import VALUE\n",
            "app/features/users/__init__.py": "VALUE = 1",
        },
    )

    found = analyze_tree(tmp_path)
    assert any(
        item.rule_id == "import-boundaries.independence"
        and item.path == "app/features/billing/__init__.py"
        for item in found
    )


# Why this test survives refactoring: a kernel outside the feature set is shared legally.
def test_features_may_import_a_shared_kernel(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/features/__init__.py": "",
            "app/features/billing/__init__.py": "from app.kernel import VALUE\n",
            "app/features/users/__init__.py": "from app.kernel import VALUE\n",
            "app/kernel/__init__.py": "VALUE = 1",
        },
    )

    assert "import-boundaries.independence" not in rule_ids(analyze_tree(tmp_path))


# Why this test survives refactoring: an indirect hop through shared still couples features.
def test_shared_module_that_imports_a_feature_breaks_independence(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/features/__init__.py": "",
            "app/features/billing/__init__.py": "from app.shared import VALUE\n",
            "app/features/users/__init__.py": "VALUE = 1",
            "app/shared/__init__.py": "from app.features.users import VALUE\n",
        },
    )

    found = analyze_tree(tmp_path, ["app/features/billing/__init__.py"])
    assert len(found) == 1
    assert found[0].rule_id == "import-boundaries.independence"
    assert found[0].path == "app/features/billing/__init__.py"
    assert "app.shared" in found[0].message
    assert "app.features.users" in found[0].message


# Why this test survives refactoring: siblings outside convention dirs are not independent.
def test_plain_siblings_are_not_an_independence_contract(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/billing.py": "from app.users import VALUE\n",
            "app/users.py": "VALUE = 1",
        },
    )

    assert "import-boundaries.independence" not in rule_ids(analyze_tree(tmp_path))


# Why this test survives refactoring: inner layers may not import outer layers.
def test_domain_importing_api_breaks_layers(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/api/__init__.py": "VALUE = 1",
            "app/domain/__init__.py": "from app.api import VALUE\n",
        },
    )

    found = analyze_tree(tmp_path)
    assert any(
        item.rule_id == "import-boundaries.layers" and item.path == "app/domain/__init__.py"
        for item in found
    )


# Why this test survives refactoring: outer siblings may wire each other.
def test_api_may_import_infrastructure(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/api/__init__.py": "from app.infrastructure import VALUE\n",
            "app/infrastructure/__init__.py": "VALUE = 1",
            "app/domain/__init__.py": "VALUE = 2",
        },
    )

    assert "import-boundaries.layers" not in rule_ids(analyze_tree(tmp_path))


# Why this test survives refactoring: the inner tier may not import the middle tier.
def test_domain_importing_services_breaks_layers(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/api/__init__.py": "",
            "app/services/__init__.py": "VALUE = 1",
            "app/domain/__init__.py": "from app.services import VALUE\n",
        },
    )

    assert any(
        item.rule_id == "import-boundaries.layers"
        and item.path == "app/domain/__init__.py"
        for item in analyze_tree(tmp_path)
    )


# Why this test survives refactoring: a missing middle tier is not a broken contract.
def test_missing_middle_tier_does_not_fail(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/api/__init__.py": "",
            "app/domain/__init__.py": "VALUE = 1",
        },
    )

    result = analyze(python_files(tmp_path), tmp_path, AnalyzerConfig())
    assert result.errors == ()
    assert "import-boundaries.layers" not in rule_ids(result.findings)


# Why this test survives refactoring: Django-shaped packages are not hexagonal.
def test_django_package_skips_layers(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/apps.py": "name = 'app'",
            "app/models.py": "VALUE = 1",
            "app/api/__init__.py": "VALUE = 2",
            "app/domain/__init__.py": "from app.api import VALUE\n",
        },
    )

    assert "import-boundaries.layers" not in rule_ids(analyze_tree(tmp_path))


# Why this test survives refactoring: a new sibling beside the layers fails exhaustive mode.
def test_helpers_sibling_fails_layers(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/api/__init__.py": "",
            "app/domain/__init__.py": "VALUE = 1",
            "app/helpers/__init__.py": "VALUE = 2",
        },
    )

    found = analyze_tree(tmp_path)
    assert any(
        item.rule_id == "import-boundaries.layers"
        and item.path == "app/helpers/__init__.py"
        and "not listed as a layer" in item.message
        for item in found
    )


# Why this test survives refactoring: production code may not import pytest.
def test_application_importing_pytest_is_forbidden(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/service.py": "import pytest\n",
            "tests/__init__.py": "import app.service\n",
        },
    )

    found = analyze_tree(tmp_path)
    assert any(
        item.rule_id == "import-boundaries.forbidden" and item.path == "app/service.py"
        for item in found
    )


# Why this test survives refactoring: tests may import the application.
def test_tests_importing_the_application_is_allowed(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "VALUE = 1",
            "tests/__init__.py": "from app import VALUE\n",
        },
    )

    assert "import-boundaries.forbidden" not in rule_ids(analyze_tree(tmp_path))


# Why this test survives refactoring: library code may not import the program entrypoint.
def test_library_importing_main_is_forbidden(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/__main__.py": "from app.lib import VALUE\n",
            "app/lib.py": "import app.__main__\nVALUE = 1",
        },
    )

    found = analyze_tree(tmp_path)
    assert any(
        item.rule_id == "import-boundaries.forbidden" and item.path == "app/lib.py"
        for item in found
    )
    assert not any(
        item.rule_id == "import-boundaries.forbidden" and item.path == "app/__main__.py"
        for item in found
    )


# Why this test survives refactoring: a cli package is an outer layer, not a program ban.
def test_importing_cli_is_not_forbidden(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/cli/__init__.py": "VALUE = 1",
            "app/lib.py": "from app.cli import VALUE\n",
        },
    )

    assert "import-boundaries.forbidden" not in rule_ids(analyze_tree(tmp_path))


# Why this test survives refactoring: the inner tier may not touch SDKs, even through a re-export.
def test_domain_sdk_import_is_forbidden_on_the_import_line(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/api/__init__.py": "",
            "app/domain/__init__.py": "",
            "app/domain/models.py": "# a\n# b\n# c\nimport sqlalchemy\n",
            "app/vendor.py": "import sqlalchemy\nVALUE = 1",
            "app/domain/reexport.py": "from app.vendor import VALUE\n",
        },
    )

    found = analyze_tree(tmp_path)
    direct = [
        item
        for item in found
        if item.path == "app/domain/models.py" and item.rule_id == "import-boundaries.forbidden"
    ]
    assert len(direct) == 1
    assert direct[0].line == 4
    assert not any(
        item.path == "app/domain/models.py" and item.rule_id == "import-boundaries.protected"
        for item in found
    )
    indirect = [
        item
        for item in found
        if item.path == "app/domain/reexport.py"
        and item.rule_id == "import-boundaries.forbidden"
    ]
    assert indirect
    assert "sqlalchemy" in indirect[0].message


# Why this test survives refactoring: SDK bans follow the hexagonal profile.
def test_sqlalchemy_is_allowed_without_hexagonal_names(tmp_path: Path) -> None:
    write(tmp_path, {"app/__init__.py": "", "app/db.py": "import sqlalchemy\n"})

    assert "import-boundaries.forbidden" not in rule_ids(analyze_tree(tmp_path))


# Why this test survives refactoring: private packages are visible to their parent only.
def test_private_package_allows_parent_and_blocks_cousin(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/users/__init__.py": "from app.users._internal import VALUE\n",
            "app/users/_internal.py": "VALUE = 1",
            "app/billing/__init__.py": "from app.users._internal import VALUE\n",
        },
    )

    found = analyze_tree(tmp_path)
    assert any(
        item.rule_id == "import-boundaries.protected"
        and item.path == "app/billing/__init__.py"
        for item in found
    )
    assert not any(
        item.rule_id == "import-boundaries.protected"
        and item.path == "app/users/__init__.py"
        for item in found
    )


# Why this test survives refactoring: application code may not import migrations.
def test_application_importing_a_migration_is_protected(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/models.py": "from app.migrations.versions.m0001 import VALUE\n",
            "app/migrations/__init__.py": "",
            "app/migrations/versions/__init__.py": "",
            "app/migrations/versions/m0001.py": "VALUE = 1",
        },
    )

    found = analyze_tree(tmp_path)
    assert any(
        item.rule_id == "import-boundaries.protected" and item.path == "app/models.py"
        for item in found
    )


# Why this test survives refactoring: SDKs are limited to the outer tier.
def test_httpx_is_protected_from_the_middle_tier(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/api/__init__.py": "import httpx\n",
            "app/services/__init__.py": "import httpx\n",
            "app/domain/__init__.py": "VALUE = 1",
        },
    )

    found = analyze_tree(tmp_path)
    assert any(
        item.rule_id == "import-boundaries.protected"
        and item.path == "app/services/__init__.py"
        for item in found
    )
    assert not any(
        item.rule_id == "import-boundaries.protected" and item.path == "app/api/__init__.py"
        for item in found
    )


# Why this test survives refactoring: untouched illegal imports stay out of a diff.
def test_unselected_cycle_is_dropped_and_all_files_reports_it(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "VALUE = 1",
            "app/left.py": "from app.right import VALUE\nVALUE = 2",
            "app/right.py": "from app.left import VALUE\nVALUE = 3",
        },
    )

    assert analyze_tree(tmp_path, ["app/__init__.py"]) == ()
    assert "import-boundaries.acyclic-siblings" in rule_ids(analyze_tree(tmp_path))


# Why this test survives refactoring: host contracts are checked with the generated ones.
def test_host_forbidden_contract_adds_a_finding(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/left.py": "from app.right import VALUE\nVALUE = 1",
            "app/right.py": "from app.left import VALUE\nVALUE = 2",
            "app/current.py": "from app.legacy import VALUE\n",
            "app/legacy.py": "VALUE = 3",
            "pyproject.toml": """
[tool.importlinter]
root_package = "app"

[[tool.importlinter.contracts]]
name = "No legacy"
type = "forbidden"
source_modules = ["app.current"]
forbidden_modules = ["app.legacy"]
as_packages = false
""",
        },
    )

    found = analyze_tree(tmp_path)
    assert "import-boundaries.acyclic-siblings" in rule_ids(found)
    assert any(
        item.rule_id.startswith("import-boundaries.")
        and item.path == "app/current.py"
        and "app.legacy" in item.message
        for item in found
    )


# Why this test survives refactoring: a bad host contract is an error, not a crash.
def test_invalid_host_contract_is_an_analyzer_error(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/left.py": "from app.right import VALUE\nVALUE = 1",
            "app/right.py": "from app.left import VALUE\nVALUE = 2",
            "pyproject.toml": """
[tool.importlinter]
root_package = "app"

[[tool.importlinter.contracts]]
name = "Broken"
type = "forbidden"
""",
        },
    )

    result = analyze(python_files(tmp_path), tmp_path, AnalyzerConfig())

    assert result.errors
    assert "Broken" in result.errors[0]
    assert "import-boundaries.acyclic-siblings" in rule_ids(result.findings)


# Why this test survives refactoring: a default run reports boundaries and ignore filters one rule.
def test_default_run_reports_boundary_and_ignore_drops_layers(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/api/__init__.py": "VALUE = 1",
            "app/domain/__init__.py": "import pytest\nfrom app.api import VALUE\n",
            "pyslop.toml": (
                "[analyzers]\ndisable = ["
                + ", ".join(
                    f'"{name}"'
                    for name in BUILTIN_ANALYZERS
                    if name != "import-boundaries"
                )
                + "]\n"
            ),
        },
    )
    files = ("app/domain/__init__.py", "app/api/__init__.py", "app/__init__.py")

    reported = run(RunOptions(repo_root=tmp_path, files=files))
    assert reported.stdout_text is not None
    assert "import-boundaries.layers" in reported.stdout_text
    assert "import-boundaries.forbidden" in reported.stdout_text
    assert "Do not hide" in reported.stdout_text

    write(
        tmp_path,
        {
            "pyslop.toml": (
                "ignore = [\"import-boundaries.layers\"]\n\n"
                "[analyzers]\ndisable = ["
                + ", ".join(
                    f'"{name}"'
                    for name in BUILTIN_ANALYZERS
                    if name != "import-boundaries"
                )
                + "]\n"
            )
        },
    )
    ignored = run(RunOptions(repo_root=tmp_path, files=files))
    assert ignored.stdout_text is not None
    assert "import-boundaries.layers" not in ignored.stdout_text
    assert "import-boundaries.forbidden" in ignored.stdout_text
