from __future__ import annotations

import shutil
from typing import Protocol

from pyslop.types import (
    DEFAULT_RUN_STAGES,
    DETECT_KIND_REGEX,
    REGEX_ANALYZER_NAME,
    STAGE_CI,
    AnalyzerSpec,
    PyslopConfig,
    ExtensionConfig,
    RuleMetadata,
)


BUILTIN_ANALYZERS = (
    "ruff",
    "pylint",
    "mypy",
    "vulture",
    "complexipy",
    "detect-secrets",
)
EXECUTABLE_MAP = {"detect-secrets": "detect-secrets-hook"}  # pragma: allowlist secret
SKIP_REASON_NOT_ON_PATH = "executable not on PATH"


class Detector(Protocol):
    def __call__(self, name: str) -> bool:
        raise NotImplementedError


BUILTIN_SPECS: dict[str, AnalyzerSpec] = {
    "ruff": AnalyzerSpec(name="ruff"),
    "pylint": AnalyzerSpec(name="pylint", stage=STAGE_CI),
    "mypy": AnalyzerSpec(name="mypy"),
    "vulture": AnalyzerSpec(name="vulture"),
    "complexipy": AnalyzerSpec(name="complexipy"),
    "detect-secrets": AnalyzerSpec(name="detect-secrets"),
}
REGEX_SPEC = AnalyzerSpec(name=REGEX_ANALYZER_NAME)


def spec_for_extension(extension: ExtensionConfig) -> AnalyzerSpec:
    return AnalyzerSpec(
        name=extension.id,
        stage=extension.stage,
        inputs=extension.inputs,
        index_roots=extension.index_roots,
    )


def stages_for_run(stage: str | None) -> frozenset[str]:
    if stage == STAGE_CI:
        return DEFAULT_RUN_STAGES | {STAGE_CI}
    return DEFAULT_RUN_STAGES


def analyzers_for_run(
    config: PyslopConfig,
    stages: frozenset[str],
    available: Detector | None = None,
    rules: dict[str, RuleMetadata] | None = None,
) -> list[AnalyzerSpec]:
    selected: list[AnalyzerSpec] = []
    for spec in get_enabled_analyzers(config, available):
        if spec.stage in stages:
            selected.append(spec)
    if (
        REGEX_ANALYZER_NAME not in config.disabled_analyzers
        and REGEX_SPEC.stage in stages
        and _has_regex_rules(rules)
    ):
        selected.append(REGEX_SPEC)
    for extension in config.extensions:
        if extension.id in config.disabled_analyzers:
            continue
        spec = spec_for_extension(extension)
        if spec.stage in stages:
            selected.append(spec)
    return selected


def skipped_builtins_for_stage(
    config: PyslopConfig,
    stages: frozenset[str],
    available: Detector | None = None,
) -> list[tuple[str, str]]:
    executable_available = available or _executable_available
    skipped: list[tuple[str, str]] = []
    for name in BUILTIN_ANALYZERS:
        if name in config.disabled_analyzers:
            continue
        spec = BUILTIN_SPECS[name]
        if spec.stage not in stages:
            continue
        if not _is_available(name, executable_available):
            skipped.append((name, SKIP_REASON_NOT_ON_PATH))
    return skipped


def _has_regex_rules(rules: dict[str, RuleMetadata] | None) -> bool:
    if not rules:
        return False
    return any(rule.detect_kind == DETECT_KIND_REGEX for rule in rules.values())


def get_enabled_analyzers(
    config: PyslopConfig,
    available: Detector | None = None,
) -> list[AnalyzerSpec]:
    executable_available = available or _executable_available
    return [
        BUILTIN_SPECS[name]
        for name in BUILTIN_ANALYZERS
        if name not in config.disabled_analyzers
        and _is_available(name, executable_available)
    ]


def _is_available(name: str, available: Detector) -> bool:
    executable_name = EXECUTABLE_MAP.get(name, name)
    return available(executable_name)


def _executable_available(name: str) -> bool:
    return shutil.which(name) is not None
