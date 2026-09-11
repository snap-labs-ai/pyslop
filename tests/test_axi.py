from pathlib import Path

import pytest

from pyslop.axi import (
    FULL_MESSAGE_CHAR_LIMIT,
    PREVIEW_MESSAGE_CHAR_LIMIT,
    parse_finding_fields,
    render_error,
    render_findings,
)
from pyslop.types import Finding, RuleMetadata


class TestRenderFindings:
    # Why this test survives refactoring: agents consume the compact AXI table, not renderer internals.
    def test_render_findings_compact_table_with_count_and_help(self) -> None:
        findings = [
            Finding("app/a.py", 10, "ruff-PLR0913", "Too many arguments"),
        ]
        rules = {
            "ruff-PLR0913": RuleMetadata(
                rule_id="ruff-PLR0913",
                fix="Group related arguments",
            ),
        }

        output = render_findings(findings, rules, bin_path="~/bin/pyslop")

        assert "bin: ~/bin/pyslop" in output
        assert "description: Unified Python static analysis for AI slop" in output
        assert "count: 1 of 1" in output
        assert "findings[1]{path,line,rule,fix,message}:" in output
        assert (
            "app/a.py,10,ruff-PLR0913,Group related arguments,Too many arguments"
            in output
        )
        assert "help[" not in output
        assert "Too many arguments" in output.split("findings[1]", 1)[1]

    def test_render_findings_states_zero_when_clean(self) -> None:
        output = render_findings([], {}, bin_path="pyslop")

        assert "findings: 0 in this file set" in output
        assert "findings[" not in output

    def test_render_findings_preview_truncates_long_messages(self) -> None:
        message = "x" * (PREVIEW_MESSAGE_CHAR_LIMIT + 10)
        findings = [Finding("app/a.py", 1, "custom", message)]

        output = render_findings(findings, {}, bin_path="pyslop")

        assert "findings[1]{path,line,rule,fix,message}:" in output
        assert f"{PREVIEW_MESSAGE_CHAR_LIMIT + 10} chars total" in output
        assert "Run `pyslop run --full` for full messages" in output

    def test_render_findings_fields_allowlist(self) -> None:
        findings = [Finding("app/a.py", 10, "custom", "Issue")]

        output = render_findings(
            findings,
            {},
            bin_path="pyslop",
            fields=("path", "line", "rule"),
        )

        assert "findings[1]{path,line,rule}:" in output
        assert "app/a.py,10,custom" in output
        assert "Issue" not in output.split("findings[1]", 1)[1]

    def test_render_findings_includes_skipped_table(self) -> None:
        output = render_findings(
            [],
            {},
            bin_path="pyslop",
            skipped=(("complexipy", "executable not on PATH"),),
        )

        assert "skipped[1]{name,reason}:" in output
        assert "complexipy,executable not on PATH" in output
        assert "pyslop analyzers" in output

    def test_parse_finding_fields_rejects_unknown(self) -> None:
        with pytest.raises(ValueError, match="unknown finding field: nope"):
            parse_finding_fields("path,nope")

    def test_render_findings_full_truncates_long_messages(self) -> None:
        message = "x" * (FULL_MESSAGE_CHAR_LIMIT + 50)
        findings = [Finding("app/a.py", 1, "custom", message)]

        output = render_findings(findings, {}, full=True, bin_path="pyslop")

        assert "findings[1]{path,line,rule,fix,message}:" in output
        assert f"{FULL_MESSAGE_CHAR_LIMIT + 50} chars total" in output

    def test_render_findings_relativizes_absolute_paths(self, tmp_path: Path) -> None:
        findings = [Finding(str(tmp_path / "app" / "a.py"), 10, "custom", "Issue")]

        output = render_findings(findings, {}, repo_root=tmp_path, bin_path="pyslop")

        assert "app/a.py,10,custom" in output


class TestRenderError:
    # Why this test survives refactoring: agents read structured errors from stdout.
    def test_render_error_includes_help(self) -> None:
        assert render_error("unknown flag --stat", "pyslop run --help") == (
            "error: unknown flag --stat\nhelp: pyslop run --help\n"
        )
