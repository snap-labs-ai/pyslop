from pathlib import Path

import pytest

from pyslop.runner import run
from pyslop.scaffold import scaffold, scaffold_extensions
from pyslop.types import RunOptions

BUILTIN_DISABLE_LIST = (
    'disable = ["ruff", "pylint", "mypy", "vulture", "complexipy", "detect-secrets", "too-many-module-functions"]'
)
_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATE_DETECT_SHIMS = (
    _REPO_ROOT / "pyslop/templates/defaults/pyslop_extensions/detect_shims"
)
_EXAMPLE_DETECT_SHIMS = _REPO_ROOT / "examples/pyslop_extensions/detect_shims"


class TestExampleDetectShimsSnapshot:
    # Why this test survives refactoring: examples/ is a published host-repo copy of the packaged template.
    def test_example_detect_shims_file_set_matches_packaged_template(self) -> None:
        template_names = {path.name for path in _TEMPLATE_DETECT_SHIMS.iterdir()}
        example_names = {path.name for path in _EXAMPLE_DETECT_SHIMS.iterdir()}

        assert example_names == template_names

    @pytest.mark.parametrize("file_name", ["__init__.py", "analyzer.py", "rules.toml"])
    def test_example_detect_shims_file_matches_packaged_template(
        self, file_name: str
    ) -> None:
        assert (
            (_EXAMPLE_DETECT_SHIMS / file_name).read_bytes()
            == (_TEMPLATE_DETECT_SHIMS / file_name).read_bytes()
        )


class TestScaffoldedDetectShimsExtension:
    # Why this test survives refactoring: it verifies the public run/scaffold contract for shim detection.
    def test_run_reports_pure_shim_with_scaffolded_detect_shims_extension(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        _scaffold_repo_with_detect_shims(tmp_path)
        (tmp_path / "app.py").write_text(
            """
def target(value):
    return value

def passthrough(value):
    return target(value)
""",
            encoding="utf-8",
        )

        # Act
        result = run(RunOptions(repo_root=tmp_path, files=("app.py",)))

        # Assert
        assert result.exit_code == 0
        assert result.findings_count == 1
        assert result.stdout_text is not None
        assert (
            "Replace callers with direct calls to the wrapped target"
            in result.stdout_text
        )

    # Why this test survives refactoring: findings are reported only for paths provided through runner discovery.
    def test_run_reports_relative_path_in_findings_for_scaffolded_detect_shims(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        _scaffold_repo_with_detect_shims(tmp_path)
        (tmp_path / "nested").mkdir()
        (tmp_path / "nested" / "shim.py").write_text(
            """
def execute(data):
    return data

def wrapper(data):
    return execute(data)
""",
            encoding="utf-8",
        )

        # Act
        result = run(RunOptions(repo_root=tmp_path, files=("nested/shim.py",)))

        # Assert
        assert result.exit_code == 0
        assert result.findings_count == 1
        assert result.stdout_text is not None
        assert "nested/shim.py" in result.stdout_text


def _scaffold_repo_with_detect_shims(tmp_path: Path) -> None:
    scaffold(tmp_path)
    scaffold_extensions(tmp_path, ("detect-shims",))
    pyslop_config = tmp_path / "pyslop.toml"
    pyslop_config.write_text(
        pyslop_config.read_text(encoding="utf-8").replace(
            "disable = []", BUILTIN_DISABLE_LIST
        ),
        encoding="utf-8",
    )
