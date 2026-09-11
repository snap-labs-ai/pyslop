from pathlib import Path

from pyslop.analyzers.regex import run
from pyslop.types import AnalyzerConfig, RuleMetadata


def _rule(rule_id: str, pattern: str, ignore: tuple[str, ...] = ()) -> RuleMetadata:
    return RuleMetadata(
        rule_id=rule_id,
        name=rule_id,
        detect_kind="regex",
        pattern=pattern,
        ignore=ignore,
    )


class TestRegexAnalyzer:
    # Why this test survives refactoring: analyzer file reads must stay bounded to the repo root.
    def test_analyze_skips_paths_resolving_outside_repo(self, tmp_path: Path) -> None:
        (tmp_path / "inside.py").write_text("# TODO: inside repo\n", encoding="utf-8")
        outside_path = tmp_path.parent / f"{tmp_path.name}_outside_regex.py"
        outside_path.write_text("# TODO: outside repo\n", encoding="utf-8")
        (tmp_path / "linked.py").symlink_to(outside_path)
        rules = {
            "slop-words.todo": _rule("slop-words.todo", r"(?i)(?:#\s*todo|//\s*todo)")
        }

        result = run(
            [
                "inside.py",
                "linked.py",
                str(outside_path),
                f"../{outside_path.name}",
            ],
            tmp_path,
            AnalyzerConfig(),
            rules=rules,
        )

        assert len(result.findings) == 1
        assert result.findings[0].path == "inside.py"

    # Why this test survives refactoring: UI placeholders are public framework APIs,
    # while TODO/stub placeholders are the slop signal.
    def test_analyze_contextual_placeholder_ignores_ui_placeholder_props(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "component.py").write_text(
            'rx.el.input(placeholder="Search projects...")\n'
            '"placeholder:text-muted-foreground/60"\n',
            encoding="utf-8",
        )
        rules = {
            "slop-words.placeholder": _rule(
                "slop-words.placeholder",
                r"(?i)(?<!\w)placeholder(?!\w).*(?:todo|stub|not implemented)|(?:todo|stub|not implemented).*(?<!\w)placeholder(?!\w)",
            )
        }

        result = run(["component.py"], tmp_path, AnalyzerConfig(), rules=rules)

        assert result.findings == ()

    # Why this test survives refactoring: it locks the intended placeholder signal
    # to explicit unfinished-code context.
    def test_analyze_contextual_placeholder_flags_todo_stub_context(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "service.py").write_text(
            "# TODO: replace placeholder implementation\n",
            encoding="utf-8",
        )
        rules = {
            "slop-words.placeholder": _rule(
                "slop-words.placeholder",
                r"(?i)(?<!\w)placeholder(?!\w).*(?:todo|stub|not implemented)|(?:todo|stub|not implemented).*(?<!\w)placeholder(?!\w)",
            )
        }

        result = run(["service.py"], tmp_path, AnalyzerConfig(), rules=rules)

        assert len(result.findings) == 1
        assert result.findings[0].rule_id == "slop-words.placeholder"
