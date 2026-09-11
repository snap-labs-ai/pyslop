from __future__ import annotations

import tomllib
from pathlib import Path

from pyslop.config import parse_rules_document
from pyslop.packaged import load_packaged_rules, merge_rules
from pyslop.path_utils import resolve_repo_path
from pyslop.types import PyslopConfig, RuleMetadata


class RulesError(Exception):
    """Raised when configured rule metadata cannot be loaded."""


def load_rules(
    config: PyslopConfig | None = None, repo_root: Path | None = None
) -> dict[str, RuleMetadata]:
    if config is None or repo_root is None:
        return {}
    rules = load_packaged_rules()
    rules = merge_rules(rules, _load_analyzer_rules(config, repo_root))
    rules = merge_rules(rules, _load_extension_rules(config, repo_root))
    return merge_rules(rules, config.rules)


def _load_analyzer_rules(
    config: PyslopConfig, repo_root: Path
) -> dict[str, RuleMetadata]:
    return _load_rules_from_configs(config.analyzer_configs, repo_root, "analyzer")


def _load_extension_rules(
    config: PyslopConfig, repo_root: Path | None
) -> dict[str, RuleMetadata]:
    if repo_root is None:
        return {}
    extension_configs = {extension.id: extension for extension in config.extensions}
    return _load_rules_from_configs(extension_configs, repo_root, "extension")


def _load_rules_from_configs(
    configs: dict[str, object], repo_root: Path, kind: str
) -> dict[str, RuleMetadata]:
    rules: dict[str, RuleMetadata] = {}
    for config_name, item_config in configs.items():
        rules_path = getattr(item_config, "rules", None)
        if not isinstance(rules_path, str) or not rules_path:
            continue
        try:
            path = resolve_repo_path(repo_root, rules_path)
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            parsed = parse_rules_document(data)
        except (
            FileNotFoundError,
            OSError,
            ValueError,
            TypeError,
            tomllib.TOMLDecodeError,
        ) as exc:
            raise RulesError(
                f"Invalid rules file for {kind} {config_name} at {rules_path}: {exc}"
            ) from exc
        rules.update(parsed)
    return rules
