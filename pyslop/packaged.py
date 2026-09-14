from __future__ import annotations

from functools import cache
from importlib import resources
from pathlib import Path
import tomllib

from pyslop.cache import cache_root, fingerprint
from pyslop.config import parse_rules_document
from pyslop.types import AnalyzerConfig, RuleMetadata

PACKAGED_ANALYZER_FILES: dict[str, tuple[str, str]] = {
    "ruff": ("ruff", "config.toml"),
    "pylint": ("pylint", "config.toml"),
    "mypy": ("mypy", "config.ini"),
    "vulture": ("vulture", "config.toml"),
    "complexipy": ("complexipy", "config.toml"),
    "detect-secrets": ("detect_secrets", "config.toml"),
    "too-many-module-functions": ("too_many_module_functions", "config.toml"),
}


def load_packaged_rules() -> dict[str, RuleMetadata]:
    rules: dict[str, RuleMetadata] = {}
    package = resources.files("pyslop")
    analyzers_root = package.joinpath("templates", "defaults", "analyzers")
    for folder, _config_name in PACKAGED_ANALYZER_FILES.values():
        rules_file = analyzers_root.joinpath(folder, "rules.toml")
        if rules_file.is_file():
            rules.update(
                parse_rules_document(_toml_dict(rules_file.read_text(encoding="utf-8")))
            )
    regex_file = package.joinpath("templates", "defaults", "regex_rules.toml")
    if regex_file.is_file():
        rules.update(
            parse_rules_document(_toml_dict(regex_file.read_text(encoding="utf-8")))
        )
    return rules


def packaged_analyzer_config(name: str, repo_root: Path) -> AnalyzerConfig:
    mapping = PACKAGED_ANALYZER_FILES.get(name)
    if mapping is None:
        return AnalyzerConfig()
    folder, filename = mapping
    materialized = _materialize_packaged_file(
        ("templates", "defaults", "analyzers", folder, filename),
        repo_root,
    )
    return AnalyzerConfig(config=str(materialized))


def merge_rules(
    base: dict[str, RuleMetadata], overlay: dict[str, RuleMetadata]
) -> dict[str, RuleMetadata]:
    merged = dict(base)
    for rule_id, overlay_rule in overlay.items():
        existing = merged.get(rule_id)
        if existing is None:
            merged[rule_id] = overlay_rule
            continue
        merged[rule_id] = RuleMetadata(
            rule_id=rule_id,
            name=overlay_rule.name or existing.name,
            fix=overlay_rule.fix or existing.fix,
            doc_links=overlay_rule.doc_links or existing.doc_links,
            detect_kind=overlay_rule.detect_kind or existing.detect_kind,
            pattern=overlay_rule.pattern or existing.pattern,
            include=overlay_rule.include or existing.include,
            ignore=overlay_rule.ignore or existing.ignore,
        )
    return merged


def _toml_dict(text: str) -> dict[str, object]:
    return tomllib.loads(text)


@cache
def _materialize_packaged_file(parts: tuple[str, ...], repo_root: Path) -> Path:
    payload = resources.files("pyslop").joinpath(*parts).read_bytes()
    key = fingerprint((b"\0".join(part.encode() for part in parts), payload))
    destination = cache_root(repo_root) / "packaged" / f"{key}{Path(parts[-1]).suffix}"
    if destination.is_file() and destination.read_bytes() == payload:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return destination
