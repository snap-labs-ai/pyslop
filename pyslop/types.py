from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import CompletedProcess


STAGE_PRE_COMMIT = "pre-commit"
STAGE_CI = "ci"
STAGE_ALWAYS = "always"
ALLOWED_STAGES = frozenset({STAGE_PRE_COMMIT, STAGE_CI, STAGE_ALWAYS})
DEFAULT_RUN_STAGES = frozenset({STAGE_PRE_COMMIT, STAGE_ALWAYS})

INPUTS_FILENAMES = "filenames"
INPUTS_INDEX = "index"
ALLOWED_INPUTS = frozenset({INPUTS_FILENAMES, INPUTS_INDEX})
DETECT_KIND_REGEX = "regex"
ALLOWED_DETECT_KINDS = frozenset({DETECT_KIND_REGEX})
REGEX_ANALYZER_NAME = "regex"

SubprocessExecutor = Callable[[Sequence[str]], CompletedProcess[str]]


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule_id: str
    message: str


@dataclass(frozen=True)
class RuleMetadata:
    rule_id: str
    name: str = ""
    fix: str = ""
    doc_links: tuple[str, ...] = ()
    detect_kind: str | None = None
    pattern: str | None = None
    include: tuple[str, ...] = ()
    ignore: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnalyzerConfig:
    config: str | None = None
    rules: str | None = None


@dataclass(frozen=True)
class AnalyzerSpec:
    name: str
    stage: str = STAGE_ALWAYS
    inputs: str = INPUTS_FILENAMES
    index_roots: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtensionConfig:
    id: str
    command: tuple[str, ...] = ()
    entry_point: str | None = None
    config: str | None = None
    rules: str | None = None
    stage: str = STAGE_ALWAYS
    inputs: str = INPUTS_FILENAMES
    index_roots: tuple[str, ...] = ()


@dataclass(frozen=True)
class PyslopConfig:
    exclude: tuple[str, ...] = ()
    disabled_analyzers: frozenset[str] = frozenset()
    analyzer_configs: dict[str, AnalyzerConfig] = field(default_factory=dict)
    extensions: tuple[ExtensionConfig, ...] = ()
    rules: dict[str, RuleMetadata] = field(default_factory=dict)
    select: tuple[str, ...] = ()
    ignore: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class DiscoveryModeFields:
    base: str = "main"
    uncommitted_only: bool = False
    path: str = ""
    files: tuple[str, ...] | None = None
    all_files: bool = False
    no_exclude: bool = False


@dataclass(frozen=True, kw_only=True)
class RunOptions(DiscoveryModeFields):
    repo_root: Path
    config_path: str | None = None
    stage: str | None = None
    files_from: str | None = None
    timings: bool = False
    no_cache: bool = False
    full: bool = False
    strict: bool = False
    fields: tuple[str, ...] | None = None


@dataclass(frozen=True)
class AnalyzerRunResult:
    findings: tuple[Finding, ...] = ()
    errors: tuple[str, ...] = ()
    skipped: tuple[tuple[str, str], ...] = ()
    timings_text: str | None = None


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    findings_count: int
    files_with_findings_count: int = 0
    errors: tuple[str, ...] = ()
    stdout_text: str | None = None
    timings_text: str | None = None
