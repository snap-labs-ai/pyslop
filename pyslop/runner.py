from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, fields
from fnmatch import fnmatch
from os import environ, pathsep
from pathlib import Path
from time import perf_counter
from typing import Protocol

from pyslop.analyzers import (
    complexipy,
    detect_secrets,
    mypy,
    pylint,
    regex,
    ruff,
    too_many_module_functions,
    vulture,
)
from pyslop.analyzers.extension import run_one_extension
from pyslop.analyzers.registry import (
    analyzers_for_run,
    skipped_builtins_for_stage,
    stages_for_run,
)
from pyslop.axi import render_analyzers, render_error, render_findings
from pyslop.cache import load_cached_result, store_cached_result
from pyslop.config import ConfigError, load_config
from pyslop.discovery import (
    DiscoveryError,
    DiscoveryOptions,
    discover_files,
    is_dot_path,
)
from pyslop.packaged import packaged_analyzer_config
from pyslop.rules_loader import RulesError, load_rules
from pyslop.types import (
    INPUTS_FILENAMES,
    INPUTS_INDEX,
    REGEX_ANALYZER_NAME,
    AnalyzerConfig,
    AnalyzerRunResult,
    AnalyzerSpec,
    DiscoveryModeFields,
    ExtensionConfig,
    Finding,
    PyslopConfig,
    RuleMetadata,
    RunOptions,
    RunResult,
)

DETECT_SECRETS_ANALYZER_NAME = "detect-secrets"
INDEX_ROOTS_ENV = "PYSLOP_INDEX_ROOTS"


LoadConfig = Callable[[Path, str | None], PyslopConfig]
DiscoverFiles = Callable[[Path, DiscoveryOptions], list[str]]
RunAnalyzers = Callable[[PyslopConfig, list[str], Path], AnalyzerRunResult]
LoadRules = Callable[[PyslopConfig, Path], dict[str, RuleMetadata]]


class AnalyzerModule(Protocol):
    def run(
        self,
        files: list[str],
        repo_root: Path,
        config: AnalyzerConfig,
        _executor: object | None = None,
    ) -> AnalyzerRunResult: ...


@dataclass(frozen=True)
class RunnerDependencies:
    load_config: LoadConfig = load_config
    discover_files: DiscoverFiles = discover_files
    run_analyzers: RunAnalyzers | None = None
    load_rules: LoadRules = load_rules


@dataclass(frozen=True)
class _AnalyzerRunParams:
    config: PyslopConfig
    files: list[str]
    repo_root: Path
    run_all: bool = False
    stages: frozenset[str] = field(
        default_factory=lambda: frozenset(stages_for_run(None))
    )
    timings: bool = False
    no_cache: bool = False
    rules: dict[str, RuleMetadata] = field(default_factory=dict)


@dataclass(frozen=True)
class _OutputParams:
    options: RunOptions
    config: PyslopConfig
    analyzer_result: AnalyzerRunResult
    rules: dict[str, RuleMetadata]
    files_with_findings_count: int
    files_count: int


def run(
    options: RunOptions, dependencies: RunnerDependencies | None = None
) -> RunResult:
    deps = dependencies or RunnerDependencies()
    try:
        config = deps.load_config(options.repo_root, options.config_path)
        discovery_options = _discovery_options(options, config)
        files = deps.discover_files(options.repo_root, discovery_options)
        rules = deps.load_rules(config, options.repo_root)
    except DiscoveryError as exc:
        return _failed_result(exc, "pyslop run --files FILE")
    except (ConfigError, RulesError) as exc:
        return _failed_result(exc, "pyslop run --help")
    analyzer_result = _run_analyzers(
        deps,
        _AnalyzerRunParams(
            config=config,
            files=files,
            repo_root=options.repo_root,
            run_all=options.all_files,
            stages=stages_for_run(options.stage),
            timings=options.timings,
            no_cache=options.no_cache,
            rules=rules,
        ),
    )
    analyzer_result = AnalyzerRunResult(
        findings=tuple(
            _filter_selected_findings(
                list(analyzer_result.findings),
                config.select,
                config.ignore,
            )
        ),
        errors=analyzer_result.errors,
        skipped=analyzer_result.skipped,
        timings_text=analyzer_result.timings_text,
    )
    files_with_findings_count = len(
        {finding.path for finding in analyzer_result.findings}
    )
    return _write_output_and_result(
        _OutputParams(
            options=options,
            config=config,
            analyzer_result=analyzer_result,
            rules=rules,
            files_with_findings_count=files_with_findings_count,
            files_count=len(files),
        )
    )


def inspect_analyzers(
    options: RunOptions, dependencies: RunnerDependencies | None = None
) -> RunResult:
    deps = dependencies or RunnerDependencies()
    help_text = "pyslop analyzers --help"
    try:
        config = deps.load_config(options.repo_root, options.config_path)
        rules = deps.load_rules(config, options.repo_root)
        discovery_options = _discovery_options(options, config)
        files = deps.discover_files(options.repo_root, discovery_options)
    except (ConfigError, DiscoveryError, RulesError) as exc:
        return _failed_result(exc, help_text)
    stages = stages_for_run(options.stage)
    params = _AnalyzerRunParams(
        config=config,
        files=files,
        repo_root=options.repo_root,
        run_all=options.all_files,
        stages=stages,
        rules=rules,
    )
    runnable: list[str] = []
    skipped = list(skipped_builtins_for_stage(config, stages))
    for spec in analyzers_for_run(config, stages, rules=rules):
        if _skip_index_analyzer(spec, params):
            skipped.append((spec.name, "no discovered path under index-roots"))
            continue
        runnable.append(spec.name)
    return RunResult(
        exit_code=0,
        findings_count=0,
        stdout_text=render_analyzers(runnable, tuple(skipped)),
    )


def _failed_result(exc: Exception, help_text: str) -> RunResult:
    return RunResult(
        exit_code=2,
        findings_count=0,
        errors=(str(exc),),
        stdout_text=render_error(str(exc), help_text),
    )


def _write_output_and_result(params: _OutputParams) -> RunResult:
    stdout_text = render_findings(
        list(params.analyzer_result.findings),
        params.rules,
        repo_root=params.options.repo_root,
        full=params.options.full,
        fields=params.options.fields,
        skipped=params.analyzer_result.skipped,
    )
    if params.analyzer_result.errors:
        error_text = "".join(
            render_error(error, "pyslop run --help")
            for error in params.analyzer_result.errors
        )
        stdout_text = error_text
        return RunResult(
            exit_code=2,
            findings_count=len(params.analyzer_result.findings),
            files_with_findings_count=params.files_with_findings_count,
            errors=params.analyzer_result.errors,
            stdout_text=stdout_text,
            timings_text=params.analyzer_result.timings_text,
        )
    findings_count = len(params.analyzer_result.findings)
    exit_code = 1 if params.options.strict and findings_count else 0
    return RunResult(
        exit_code=exit_code,
        findings_count=findings_count,
        files_with_findings_count=params.files_with_findings_count,
        stdout_text=stdout_text,
        timings_text=params.analyzer_result.timings_text,
    )


def _discovery_options(options: RunOptions, config: PyslopConfig) -> DiscoveryOptions:
    mode_fields = {
        dmf.name: getattr(options, dmf.name) for dmf in fields(DiscoveryModeFields)
    }
    mode_fields["files"] = _explicit_file_targets(options)
    return DiscoveryOptions(excludes=config.exclude, **mode_fields)


def _explicit_file_targets(options: RunOptions) -> tuple[str, ...] | None:
    listed: list[str] = list(options.files or ())
    if options.files_from:
        path = Path(options.files_from)
        if not path.is_absolute():
            path = options.repo_root / path
        listed.extend(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    if listed:
        return tuple(listed)
    return None


def _run_analyzers(
    deps: RunnerDependencies,
    params: _AnalyzerRunParams,
) -> AnalyzerRunResult:
    if deps.run_analyzers:
        return deps.run_analyzers(params.config, params.files, params.repo_root)
    findings: list[Finding] = []
    errors: list[str] = []
    skipped: list[tuple[str, str]] = list(
        skipped_builtins_for_stage(params.config, params.stages)
    )
    timing_lines: list[str] = []
    analyzer_modules = {
        "ruff": ruff,
        "pylint": pylint,
        "mypy": mypy,
        "vulture": vulture,
        "complexipy": complexipy,
        DETECT_SECRETS_ANALYZER_NAME: detect_secrets,
        "too-many-module-functions": too_many_module_functions,
    }
    for spec in analyzers_for_run(params.config, params.stages, rules=params.rules):
        if _skip_index_analyzer(spec, params):
            skipped.append((spec.name, "no discovered path under index-roots"))
            continue
        started = perf_counter()
        result = _run_one_spec(spec, params, analyzer_modules)
        elapsed = perf_counter() - started
        if params.timings:
            timing_lines.append(f"{spec.name} {elapsed:.3f}s")
        findings.extend(
            _filter_findings(result.findings, params.files, params.repo_root)
        )
        skip_rows, public_errors = _partition_analyzer_outcome(spec.name, result)
        skipped.extend(skip_rows)
        errors.extend(public_errors)
    timings_text = "\n".join(timing_lines) if timing_lines else None
    return AnalyzerRunResult(
        findings=tuple(findings),
        errors=tuple(errors),
        skipped=tuple(skipped),
        timings_text=timings_text,
    )


def _partition_analyzer_outcome(
    name: str, result: AnalyzerRunResult
) -> tuple[list[tuple[str, str]], list[str]]:
    skipped = list(result.skipped)
    errors: list[str] = []
    for error in result.errors:
        if _looks_like_cannot_start(error):
            skipped.append((name, "executable not on PATH"))
            continue
        errors.append(_public_started_error(error))
    return skipped, errors


def _looks_like_cannot_start(error: str) -> bool:
    lowered = error.lower()
    return (
        "winerror" in lowered
        or "cannot find the file" in lowered
        or "errno 2" in lowered
    )


def _public_started_error(error: str) -> str:
    if "WinError" in error or "Errno 2" in error:
        name = error.split(" ", 1)[0]
        return f"{name} failed after start"
    return error


def _run_one_spec(
    spec: AnalyzerSpec,
    params: _AnalyzerRunParams,
    analyzer_modules: dict[str, AnalyzerModule],
) -> AnalyzerRunResult:
    config_bytes = _analyzer_config_bytes(params, spec)
    if not params.no_cache:
        cached = load_cached_result(params.repo_root, spec, params.files, config_bytes)
        if cached is not None:
            return cached
    if spec.name == REGEX_ANALYZER_NAME:
        result = regex.run(
            _targets_for_analyzer(spec, params),
            params.repo_root,
            AnalyzerConfig(),
            rules=params.rules,
        )
    elif spec.name in analyzer_modules:
        module = analyzer_modules[spec.name]
        result = module.run(
            _targets_for_analyzer(spec, params),
            params.repo_root,
            _resolved_analyzer_config(params, spec),
        )
    else:
        extension = _extension_by_id(params.config, spec.name)
        if extension is None:
            return AnalyzerRunResult(
                errors=(f"analyzer {spec.name} is not a builtin or extension",)
            )
        with _index_roots_environ(spec):
            result = run_one_extension(extension, params.files, params.repo_root)
    if not params.no_cache:
        store_cached_result(params.repo_root, spec, params.files, config_bytes, result)
    return result


def _resolved_analyzer_config(
    params: _AnalyzerRunParams, spec: AnalyzerSpec
) -> AnalyzerConfig:
    overlay = params.config.analyzer_configs.get(spec.name, AnalyzerConfig())
    if overlay.config:
        overlay_path = params.repo_root / overlay.config
        if overlay_path.is_file():
            return overlay
    packaged = packaged_analyzer_config(spec.name, params.repo_root)
    return AnalyzerConfig(config=packaged.config, rules=overlay.rules)


def _analyzer_config_bytes(params: _AnalyzerRunParams, spec: AnalyzerSpec) -> bytes:
    rules_payload = _rules_fingerprint(params.rules)
    if spec.name == REGEX_ANALYZER_NAME:
        return rules_payload
    analyzer_config = _resolved_analyzer_config(params, spec)
    config_path = analyzer_config.config
    if config_path is None:
        extension = _extension_by_id(params.config, spec.name)
        config_path = extension.config if extension else None
    config_bytes = b""
    if config_path:
        path = Path(config_path)
        if not path.is_absolute():
            path = params.repo_root / path
        if path.is_file():
            config_bytes = path.read_bytes()
    return config_bytes + b"\0" + rules_payload


def _rules_fingerprint(rules: dict[str, RuleMetadata]) -> bytes:
    payload = tuple(
        (
            rule.rule_id,
            rule.name,
            rule.fix,
            rule.detect_kind,
            rule.pattern,
            rule.include,
            rule.ignore,
        )
        for rule in sorted(rules.values(), key=lambda item: item.rule_id)
    )
    return repr(payload).encode("utf-8")


def _filter_selected_findings(
    findings: list[Finding],
    select: tuple[str, ...],
    ignore: tuple[str, ...],
) -> list[Finding]:
    kept: list[Finding] = []
    for finding in findings:
        if ignore and any(fnmatch(finding.rule_id, pattern) for pattern in ignore):
            continue
        if select and not any(fnmatch(finding.rule_id, pattern) for pattern in select):
            continue
        kept.append(finding)
    return kept


def _filter_findings(
    findings: tuple[Finding, ...], files: list[str], repo_root: Path
) -> list[Finding]:
    discovered = {_normalize_relative_path(path, repo_root) for path in files}
    basename_to_paths = _basename_to_paths(discovered)
    kept: list[Finding] = []
    for finding in findings:
        normalized = _normalize_relative_path(finding.path, repo_root)
        if is_dot_path(normalized):
            continue
        resolved = _resolve_finding_path(normalized, discovered, basename_to_paths)
        if resolved:
            kept.append(
                Finding(
                    path=resolved,
                    line=finding.line,
                    rule_id=finding.rule_id,
                    message=finding.message,
                )
            )
    return kept


def _basename_to_paths(paths: set[str]) -> dict[str, tuple[str, ...]]:
    basename_to_paths: dict[str, list[str]] = {}
    for path in paths:
        basename = Path(path).name
        basename_to_paths.setdefault(basename, []).append(path)
    return {name: tuple(values) for name, values in basename_to_paths.items()}


def _resolve_finding_path(
    normalized_path: str,
    discovered_paths: set[str],
    basename_to_paths: dict[str, tuple[str, ...]],
) -> str | None:
    if normalized_path in discovered_paths:
        return normalized_path

    matches = basename_to_paths.get(Path(normalized_path).name, ())
    if len(matches) == 1:
        return matches[0]
    return None


def _normalize_relative_path(path: str, repo_root: Path) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(repo_root)
        except ValueError:
            return candidate.as_posix()
    return candidate.as_posix()


def _targets_for_analyzer(spec: AnalyzerSpec, params: _AnalyzerRunParams) -> list[str]:
    _ = spec
    return params.files


def _skip_index_analyzer(spec: AnalyzerSpec, params: _AnalyzerRunParams) -> bool:
    inputs = getattr(spec, "inputs", INPUTS_FILENAMES)
    if inputs != INPUTS_INDEX:
        return False
    if params.run_all:
        return False
    roots = getattr(spec, "index_roots", ())
    return not any(_path_under_index_roots(path, roots) for path in params.files)


def _path_under_index_roots(file_path: str, index_roots: tuple[str, ...]) -> bool:
    posix = Path(file_path).as_posix()
    for root in index_roots:
        prefix = Path(root).as_posix().rstrip("/")
        if prefix in {".", ""}:
            return True
        if posix == prefix or posix.startswith(f"{prefix}/"):
            return True
    return False


@contextmanager
def _index_roots_environ(spec: AnalyzerSpec) -> Iterator[None]:
    if spec.inputs != INPUTS_INDEX or not spec.index_roots:
        yield
        return
    previous = environ.get(INDEX_ROOTS_ENV)
    environ[INDEX_ROOTS_ENV] = pathsep.join(spec.index_roots)
    try:
        yield
    finally:
        if previous is None:
            environ.pop(INDEX_ROOTS_ENV, None)
        else:
            environ[INDEX_ROOTS_ENV] = previous


def _extension_by_id(config: PyslopConfig, analyzer_id: str) -> ExtensionConfig | None:
    for extension in config.extensions:
        if extension.id == analyzer_id:
            return extension
    return None
