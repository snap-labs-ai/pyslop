from pathlib import Path

import pytest

from pyslop.runner import run
from pyslop.scaffold import scaffold
from pyslop.types import RunOptions

BUILTIN_DISABLE_LIST = (
    'disable = ["ruff", "pylint", "mypy", "vulture", "complexipy", "detect-secrets"]'
)
AGENTIC_RULE = """
[[rules]]
id = "slop-words.agentic"
name = "Trigger word: agentic"
fix = "Replace vague agent language with specific behavior."
detect = { kind = "regex", pattern = "(?i)(?<!\\\\w)agentic(?!\\\\w)" }
"""
HACK_IGNORE_RULE = """
select = ["custom.hack"]
[[rules]]
id = "custom.hack"
name = "Trigger word: hack"
fix = "Replace hacks."
detect = { kind = "regex", pattern = "(?i)(?<!\\\\w)hack(?!\\\\w)", ignore = ["app.py"] }
"""


class TestRegexRules:
    # Why this test survives refactoring: packaged slop-word regex is observed through the public runner.
    def test_run_reports_packaged_slop_words_with_rule_metadata(
        self, tmp_path: Path
    ) -> None:
        _repo_with_regex(tmp_path, "")
        (tmp_path / "app.py").write_text("# TODO: remove hack\n", encoding="utf-8")

        result = run(RunOptions(repo_root=tmp_path, files=("app.py",)))

        assert result.exit_code == 0
        assert result.findings_count == 2
        assert result.stdout_text is not None
        assert "slop-words.todo" in result.stdout_text
        assert "slop-words.hack" in result.stdout_text
        assert "Resolve the TODO before shipping." in result.stdout_text

    # Why this test survives refactoring: overlay rules add detection without a Python extension.
    def test_run_reports_user_added_regex_rule(self, tmp_path: Path) -> None:
        _repo_with_regex(tmp_path, AGENTIC_RULE)
        (tmp_path / "app.py").write_text("# agentic workflow\n", encoding="utf-8")

        result = run(RunOptions(repo_root=tmp_path, files=("app.py",)))

        assert result.exit_code == 0
        assert result.stdout_text is not None
        assert "slop-words.agentic" in result.stdout_text
        assert (
            "Replace vague agent language with specific behavior." in result.stdout_text
        )

    @pytest.mark.parametrize(
        ("file_name", "file_content"),
        [
            ("notes.md", "TODO: markdown note\n"),
            ("settings.toml", "note = 'TODO config'\n"),
            (".gitignore", "TODO hidden file\n"),
        ],
    )
    # Why this test survives refactoring: default ignore patterns are validated through public run behavior.
    def test_run_ignores_markdown_and_toml_files_by_default(
        self, tmp_path: Path, file_name: str, file_content: str
    ) -> None:
        _repo_with_regex(tmp_path, "")
        (tmp_path / file_name).write_text(file_content, encoding="utf-8")

        result = run(RunOptions(repo_root=tmp_path, files=(file_name,)))

        assert result.exit_code == 0
        assert result.findings_count == 0

    # Why this test survives refactoring: ignore globs on a user regex rule are public behavior.
    def test_run_honors_ignore_globs_on_user_rule(self, tmp_path: Path) -> None:
        _repo_with_regex(tmp_path, HACK_IGNORE_RULE)
        (tmp_path / "app.py").write_text("# TODO: remove hack\n", encoding="utf-8")

        result = run(RunOptions(repo_root=tmp_path, files=("app.py",)))

        assert result.exit_code == 0
        assert result.findings_count == 0

    # Why this test survives refactoring: whole-word matching is externally observable via findings.
    def test_run_matches_whole_word_not_substring_for_temp_trigger(
        self, tmp_path: Path
    ) -> None:
        _repo_with_regex(tmp_path, 'select = ["slop-words.temp"]\n')
        (tmp_path / "app.py").write_text(
            'value = "attempt"\nlabel = "temp"\n', encoding="utf-8"
        )

        result = run(RunOptions(repo_root=tmp_path, files=("app.py",)))

        assert result.exit_code == 0
        assert result.findings_count == 1
        assert result.stdout_text is not None
        assert "slop-words.temp" in result.stdout_text


def _repo_with_regex(tmp_path: Path, extra: str) -> None:
    scaffold(tmp_path, "cursor")
    pyslop_config = tmp_path / "pyslop.toml"
    text = pyslop_config.read_text(encoding="utf-8").replace(
        "disable = []", BUILTIN_DISABLE_LIST
    )
    if extra.strip():
        text = text.replace("exclude = []", f"exclude = []\n{extra.strip()}", 1)
    pyslop_config.write_text(text, encoding="utf-8")
