from __future__ import annotations

import tomllib
from dataclasses import replace

from pyslop.types import (
    ALLOWED_DETECT_KINDS,
    ALLOWED_INPUTS,
    ALLOWED_STAGES,
    INPUTS_FILENAMES,
    INPUTS_INDEX,
    STAGE_ALWAYS,
    AnalyzerConfig,
    PyslopConfig,
    ExtensionConfig,
    RuleMetadata,
)


class ConfigError(Exception):
    """Raised when pyslop.toml cannot be parsed or validated."""


def load_config(repo_root: Path, config_path: str | Path | None = None) -> PyslopConfig:
    path = Path(config_path) if config_path else repo_root / "pyslop.toml"
    if not path.exists():
        return PyslopConfig()
    try:
        with path.open("rb") as config_file:
            data = tomllib.load(config_file)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc
    try:
        return _parse_config(data)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid pyslop config in {path}: {exc}") from exc


def _parse_config(data: dict[str, object]) -> PyslopConfig:
    analyzers = _table(data.get("analyzers"), "analyzers", default={})
    return PyslopConfig(
        exclude=_string_tuple(data.get("exclude", ()), "exclude"),
        disabled_analyzers=frozenset(
            _string_tuple(analyzers.get("disable", ()), "analyzers.disable")
        ),
        analyzer_configs=_parse_analyzer_configs(analyzers),
        extensions=_parse_extensions(analyzers.get("extensions", ())),
        rules=_parse_rules_value(data.get("rules")),
        select=_string_tuple(data.get("select", ()), "select"),
        ignore=_string_tuple(data.get("ignore", ()), "ignore"),
    )


def _parse_analyzer_configs(analyzers: dict[str, object]) -> dict[str, AnalyzerConfig]:
    configs: dict[str, AnalyzerConfig] = {}
    for name, value in analyzers.items():
        if name in {"disable", "extensions"}:
            continue
        table = _table(value, f"analyzers.{name}")
        config = _optional_string(table.get("config"), f"analyzers.{name}.config")
        rules = _optional_string(table.get("rules"), f"analyzers.{name}.rules")
        configs[name] = AnalyzerConfig(config=config, rules=rules)
    return configs


def _parse_extensions(value: object) -> tuple[ExtensionConfig, ...]:
    if value in (None, ()):
        return ()
    if not isinstance(value, list):
        raise TypeError("analyzers.extensions must be a list of tables")
    return tuple(_parse_extension(item, index) for index, item in enumerate(value))


def _parse_extension(value: object, index: int) -> ExtensionConfig:
    table = _table(value, f"analyzers.extensions[{index}]")
    extension_id = _required_string(
        table.get("id"), f"analyzers.extensions[{index}].id"
    )
    command = _string_tuple(
        table.get("command", ()), f"analyzers.extensions[{index}].command"
    )
    entry_point = _optional_string(
        table.get("entry-point") or table.get("entry_point"),
        f"analyzers.extensions[{index}].entry-point",
    )
    config = _optional_string(
        table.get("config"), f"analyzers.extensions[{index}].config"
    )
    rules = _optional_string(table.get("rules"), f"analyzers.extensions[{index}].rules")
    if bool(command) == bool(entry_point):
        raise ValueError(
            "each extension must define exactly one of command or entry-point"
        )
    stage = (
        _optional_string(table.get("stage"), f"analyzers.extensions[{index}].stage")
        or STAGE_ALWAYS
    )
    inputs = (
        _optional_string(table.get("inputs"), f"analyzers.extensions[{index}].inputs")
        or INPUTS_FILENAMES
    )
    if stage not in ALLOWED_STAGES:
        raise ValueError(
            f"analyzers.extensions[{index}].stage must be one of "
            f"{sorted(ALLOWED_STAGES)}"
        )
    if inputs not in ALLOWED_INPUTS:
        raise ValueError(
            f"analyzers.extensions[{index}].inputs must be one of "
            f"{sorted(ALLOWED_INPUTS)}"
        )
    index_roots = _string_tuple(
        table.get("index-roots", table.get("index_roots", ())),
        f"analyzers.extensions[{index}].index-roots",
    )
    if inputs == INPUTS_INDEX and not index_roots:
        raise ValueError(
            f"analyzers.extensions[{index}].index-roots is required when "
            "inputs is index"
        )
    if "serial" in table:
        raise ValueError(f"analyzers.extensions[{index}].serial is not supported")
    return ExtensionConfig(
        id=extension_id,
        command=command,
        entry_point=entry_point,
        config=config,
        rules=rules,
        stage=stage,
        inputs=inputs,
        index_roots=index_roots,
    )


def parse_rules_document(data: dict[str, object]) -> dict[str, RuleMetadata]:
    shared_ignore = _string_tuple(data.get("ignore", ()), "ignore")
    rules = _parse_rules_value(data.get("rules"))
    if not shared_ignore:
        return rules
    merged: dict[str, RuleMetadata] = {}
    for rule_id, rule in rules.items():
        ignore = tuple(dict.fromkeys((*shared_ignore, *rule.ignore)))
        merged[rule_id] = replace(rule, ignore=ignore)
    return merged


def _parse_rules_value(value: object) -> dict[str, RuleMetadata]:
    if value in (None, (), {}):
        return {}
    if isinstance(value, list):
        return _parse_rules_array(value)
    return _parse_rules(_table(value, "rules"))


def _parse_rules_array(value: list[object]) -> dict[str, RuleMetadata]:
    rules: dict[str, RuleMetadata] = {}
    for index, item in enumerate(value):
        table = _table(item, f"rules[{index}]")
        rule_id = _required_string(table.get("id"), f"rules[{index}].id")
        rules[rule_id] = _rule_from_table(rule_id, table, f"rules[{index}]")
    return rules


def _parse_rules(value: dict[str, object]) -> dict[str, RuleMetadata]:
    rules: dict[str, RuleMetadata] = {}
    for rule_id, rule_value in value.items():
        table = _table(rule_value, f"rules.{rule_id}")
        rules[rule_id] = _rule_from_table(rule_id, table, f"rules.{rule_id}")
    return rules


def _rule_from_table(
    rule_id: str, table: dict[str, object], prefix: str
) -> RuleMetadata:
    detect = table.get("detect")
    detect_kind: str | None = None
    pattern: str | None = None
    include: tuple[str, ...] = ()
    ignore: tuple[str, ...] = _string_tuple(table.get("ignore", ()), f"{prefix}.ignore")
    if detect is not None:
        detect_table = _table(detect, f"{prefix}.detect")
        detect_kind = _required_string(
            detect_table.get("kind"), f"{prefix}.detect.kind"
        )
        if detect_kind not in ALLOWED_DETECT_KINDS:
            allowed = ", ".join(sorted(ALLOWED_DETECT_KINDS))
            raise ValueError(
                f"{prefix}.detect.kind must be one of: {allowed} (got {detect_kind})"
            )
        pattern = _required_string(
            detect_table.get("pattern"), f"{prefix}.detect.pattern"
        )
        include = _string_tuple(
            detect_table.get("include", ()), f"{prefix}.detect.include"
        )
        detect_ignore = _string_tuple(
            detect_table.get("ignore", ()), f"{prefix}.detect.ignore"
        )
        if detect_ignore:
            ignore = detect_ignore
    return RuleMetadata(
        rule_id=rule_id,
        name=_optional_string(table.get("name"), f"{prefix}.name") or "",
        fix=_optional_string(table.get("fix"), f"{prefix}.fix") or "",
        doc_links=_string_tuple(
            table.get("doc-links", table.get("doc_links", ())),
            f"{prefix}.doc-links",
        ),
        detect_kind=detect_kind,
        pattern=pattern,
        include=include,
        ignore=ignore,
    )


def _table(
    value: object, name: str, default: dict[str, object] | None = None
) -> dict[str, object]:
    if value is None and default is not None:
        return default
    if isinstance(value, dict):
        return value
    raise TypeError(f"{name} must be a table")


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    if value in (None, ()):
        return ()
    raise TypeError(f"{name} must be a list of strings")


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise TypeError(f"{name} must be a string")


def _required_string(value: object, name: str) -> str:
    result = _optional_string(value, name)
    if not result:
        raise ValueError(f"{name} is required")
    return result


def _optional_bool(value: object, name: str) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raise TypeError(f"{name} must be a boolean")
