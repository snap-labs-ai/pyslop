from collections.abc import Sequence
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess

import pytest

from pyslop.discovery import (
    DiscoveryError,
    DiscoveryOptions,
    apply_excludes,
    discover_files,
)


class TestApplyExcludes:
    # Why this test survives refactoring: exclude matching is a public pure-function contract.
    def test_apply_excludes_removes_matching_paths(self) -> None:
        # Arrange
        files = ["app/main.py", "alembic/env.py", "scripts/audit.py"]

        # Act
        filtered = apply_excludes(files, ["alembic/**", "scripts/**"])

        # Assert
        assert filtered == ["app/main.py"]

    # Why this test survives refactoring: empty excludes must leave caller-provided order intact.
    def test_apply_excludes_retains_all_paths_without_patterns(self) -> None:
        # Arrange
        files = ["app/main.py", "scripts/audit.py"]

        # Act
        filtered = apply_excludes(files, [])

        # Assert
        assert filtered == files


class TestDiscoverFiles:
    # Why this test survives refactoring: it checks the default observable file set returned from git data.
    def test_discover_files_returns_base_and_uncommitted_changes_once(
        self,
        tmp_path: Path,
    ) -> None:
        # Arrange
        create_files(
            tmp_path,
            "app/committed.py",
            "app/staged.py",
            "app/unstaged.py",
            "app/untracked.py",
            "pyslop.toml",
        )
        executor = FakeGit(
            {
                (
                    "git",
                    "diff",
                    "--name-only",
                    "--diff-filter=d",
                    "main...HEAD",
                ): "app/committed.py\napp/staged.py\nmissing.py\npyslop.toml\n",
                ("git", "diff", "--name-only", "--diff-filter=d"): "app/unstaged.py\n",
                (
                    "git",
                    "diff",
                    "--cached",
                    "--name-only",
                    "--diff-filter=d",
                ): "app/staged.py\n",
                (
                    "git",
                    "ls-files",
                    "--others",
                    "--exclude-standard",
                ): "app/untracked.py\n",
            }
        )

        # Act
        files = discover_files(tmp_path, DiscoveryOptions(base="main"), executor.run)

        # Assert
        assert files == [
            "app/committed.py",
            "app/staged.py",
            "pyslop.toml",
            "app/unstaged.py",
            "app/untracked.py",
        ]

    # Why this test survives refactoring: git-diff discovery must expose all existing changed file types.
    def test_discover_files_includes_non_python_files_from_git_diff(
        self,
        tmp_path: Path,
    ) -> None:
        # Arrange
        create_files(tmp_path, "app/config.yaml", "app/main.py")
        executor = FakeGit(
            {
                (
                    "git",
                    "diff",
                    "--name-only",
                    "--diff-filter=d",
                    "main...HEAD",
                ): "app/config.yaml\napp/main.py\n",
                ("git", "diff", "--name-only", "--diff-filter=d"): "",
                ("git", "diff", "--cached", "--name-only", "--diff-filter=d"): "",
                ("git", "ls-files", "--others", "--exclude-standard"): "",
            }
        )

        # Act
        files = discover_files(tmp_path, DiscoveryOptions(base="main"), executor.run)

        # Assert
        assert files == ["app/config.yaml", "app/main.py"]

    # Why this test survives refactoring: path restriction is an observable discovery option.
    def test_discover_files_restricts_git_changes_to_path(self, tmp_path: Path) -> None:
        # Arrange
        create_files(tmp_path, "app/features/a.py", "app/other.py")
        executor = FakeGit(
            {
                (
                    "git",
                    "diff",
                    "--name-only",
                    "--diff-filter=d",
                    "main...HEAD",
                ): "app/features/a.py\napp/other.py\n",
                ("git", "diff", "--name-only", "--diff-filter=d"): "",
                ("git", "diff", "--cached", "--name-only", "--diff-filter=d"): "",
                ("git", "ls-files", "--others", "--exclude-standard"): "",
            }
        )

        # Act
        files = discover_files(
            tmp_path, DiscoveryOptions(path="app/features/"), executor.run
        )

        # Assert
        assert files == ["app/features/a.py"]

    # Why this test survives refactoring: uncommitted mode excludes base-only branch changes.
    def test_discover_files_uncommitted_only_excludes_committed_changes(
        self,
        tmp_path: Path,
    ) -> None:
        # Arrange
        create_files(
            tmp_path,
            "app/committed.py",
            "app/staged.py",
            "app/unstaged.py",
            "app/untracked.py",
        )
        executor = FakeGit(
            {
                ("git", "diff", "--name-only", "--diff-filter=d"): "app/unstaged.py\n",
                (
                    "git",
                    "diff",
                    "--cached",
                    "--name-only",
                    "--diff-filter=d",
                ): "app/staged.py\n",
                (
                    "git",
                    "ls-files",
                    "--others",
                    "--exclude-standard",
                ): "app/untracked.py\n",
            }
        )

        # Act
        files = discover_files(
            tmp_path, DiscoveryOptions(uncommitted_only=True), executor.run
        )

        # Assert
        assert files == ["app/unstaged.py", "app/staged.py", "app/untracked.py"]

    # Why this test survives refactoring: no-exclude must bypass config filtering in all modes.
    def test_discover_files_no_exclude_retains_matching_files(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        create_files(tmp_path, "app/a.py", "scripts/audit.py")

        # Act
        files = discover_files(
            tmp_path,
            DiscoveryOptions(all_files=True, excludes=("scripts/**",), no_exclude=True),
            FakeGit({}).run,
        )

        # Assert
        assert files == ["app/a.py", "scripts/audit.py"]

    # Why this test survives refactoring: all-files discovery must expose all existing file types.
    def test_discover_files_all_files_includes_non_python_files(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        create_files(tmp_path, "app/a.py", "app/b.txt", "other.py")

        # Act
        files = discover_files(
            tmp_path,
            DiscoveryOptions(all_files=True),
            FailingGit().run,
        )

        # Assert
        assert files == ["app/a.py", "app/b.txt", "other.py"]

    # Why this test survives refactoring: explicit modes are required to work without git.
    def test_discover_files_explicit_modes_do_not_invoke_git(
        self,
        tmp_path: Path,
    ) -> None:
        # Arrange
        create_files(tmp_path, "app/a.py", "app/b.txt", "other.py")

        # Act
        all_files = discover_files(
            tmp_path, DiscoveryOptions(all_files=True), FailingGit().run
        )
        path_files = discover_files(
            tmp_path, DiscoveryOptions(files=("app",)), FailingGit().run
        )

        # Assert
        assert all_files == ["app/a.py", "app/b.txt", "other.py"]
        assert path_files == ["app/a.py", "app/b.txt"]

    # Why this test survives refactoring: explicit mode must preserve caller-provided file ordering.
    def test_discover_files_returns_multiple_explicit_files_in_order(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        create_files(tmp_path, "backend/b.py", "app/a.py")

        # Act
        files = discover_files(
            tmp_path,
            DiscoveryOptions(files=("app/a.py", "backend/b.py")),
            FailingGit().run,
        )

        # Assert
        assert files == ["app/a.py", "backend/b.py"]

    # Why this test survives refactoring: explicit targets can mix directories and files.
    def test_discover_files_expands_directory_and_preserves_explicit_file(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        create_files(tmp_path, "app/a.py", "app/b.py", "backend/c.py")

        # Act
        files = discover_files(
            tmp_path,
            DiscoveryOptions(files=("app", "backend/c.py")),
            FailingGit().run,
        )

        # Assert
        assert files == ["app/a.py", "app/b.py", "backend/c.py"]

    # Why this test survives refactoring: git command failures must not crash discovery mode.
    def test_discover_files_returns_untracked_when_base_git_diff_fails(
        self,
        tmp_path: Path,
    ) -> None:
        # Arrange
        create_files(tmp_path, "app/untracked.py")
        executor = FailingBaseGit()

        # Act
        files = discover_files(tmp_path, DiscoveryOptions(base="main"), executor.run)

        # Assert
        assert files == ["app/untracked.py"]

    def test_discover_files_raises_when_not_a_git_work_tree(self, tmp_path: Path) -> None:
        class NotGit:
            def run(self, command: Sequence[str]) -> CompletedProcess[str]:
                raise CalledProcessError(128, cmd=list(command), stderr="not a git repository")

        create_files(tmp_path, "app/a.py")

        with pytest.raises(DiscoveryError, match="not a git repository"):
            discover_files(tmp_path, DiscoveryOptions(base="main"), NotGit().run)


class FakeGit:
    def __init__(self, outputs: dict[tuple[str, ...], str]) -> None:
        self.outputs = outputs

    def run(self, command: Sequence[str]) -> CompletedProcess[str]:
        if list(command) == ["git", "rev-parse", "--is-inside-work-tree"]:
            return CompletedProcess(command, 0, stdout="true\n", stderr="")
        key = tuple(command)
        return CompletedProcess(command, 0, stdout=self.outputs.get(key, ""), stderr="")


class FailingGit:
    def run(self, command: Sequence[str]) -> CompletedProcess[str]:
        raise AssertionError(f"git should not be invoked: {command}")


class FailingBaseGit:
    def run(self, command: Sequence[str]) -> CompletedProcess[str]:
        if list(command) == ["git", "rev-parse", "--is-inside-work-tree"]:
            return CompletedProcess(command, 0, stdout="true\n", stderr="")
        if (
            list(command[:3]) == ["git", "diff", "--name-only"]
            and "main...HEAD" in command
        ):
            raise CalledProcessError(returncode=128, cmd=command, stderr="bad revision")
        if list(command) == ["git", "ls-files", "--others", "--exclude-standard"]:
            return CompletedProcess(command, 0, stdout="app/untracked.py\n", stderr="")
        return CompletedProcess(command, 0, stdout="", stderr="")


def create_files(root: Path, *paths: str) -> None:
    for relative_path in paths:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content", encoding="utf-8")
