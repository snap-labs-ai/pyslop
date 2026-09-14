from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLE_PRE_COMMIT = _REPO_ROOT / "examples/.pre-commit-config.yaml"
_REPO_PRE_COMMIT = _REPO_ROOT / ".pre-commit-config.yaml"
_CI = _REPO_ROOT / "examples/ci.yaml"
_GIT_INSTALL = "uv add \"pyslop[analyzers] @ git+https://github.com/snap-labs-ai/pyslop.git\""


# Why this test survives refactoring: published examples are the public third-party gate contract.
def test_example_pre_commit_hook_is_third_party_git_install() -> None:
    text = _EXAMPLE_PRE_COMMIT.read_text(encoding="utf-8")
    assert _GIT_INSTALL in text
    assert "entry: uv run pyslop run --strict" in text
    assert "--files" not in text
    assert "language: system" in text
    assert "--extra analyzers" not in text


# Why this test survives refactoring: this repo dogfoods via a local uv run hook, not the example file.
def test_repo_pre_commit_hook_runs_in_tree_cli() -> None:
    text = _REPO_PRE_COMMIT.read_text(encoding="utf-8")
    assert "git+" not in text
    assert "uv sync --group dev --extra analyzers" in text
    assert "entry: uv run pyslop run --strict" in text
    assert "--files" not in text
    assert "language: system" in text


# Why this test survives refactoring: CI example must show whole-repo and changed-file --strict gates after uv add.
def test_example_ci_workflow_shows_all_and_changed_jobs() -> None:
    text = _CI.read_text(encoding="utf-8")
    assert _GIT_INSTALL in text
    assert "uvx pre-commit" not in text
    assert "uv sync --extra analyzers" not in text
    assert "uv sync\n" in text.replace("\r\n", "\n")
    assert "pyslop run --all --stage ci --strict" in text
    assert 'pyslop run --stage ci --strict --base "origin/${BASE_REF}"' in text
    assert "pyslop-all:" in text
    assert "pyslop-changed:" in text
