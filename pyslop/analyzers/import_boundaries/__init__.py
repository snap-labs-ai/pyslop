from __future__ import annotations

import importlib
import importlib.util
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Protocol

from grimp import ImportGraph

from pyslop.analyzers.base import PYTHON_SOURCE_SUFFIXES
from pyslop.analyzers.import_boundaries.discover import (
    RootPackage,
    discover_root_packages,
)
from pyslop.analyzers.import_boundaries.plan import (
    RULES,
    ContractSources,
    PlannedContract,
    needs_external_packages,
    plan_contracts,
)
from pyslop.types import AnalyzerConfig, AnalyzerRunResult, Finding


class _HostConfig(Protocol):
    session_options: Mapping[str, object]
    contracts_options: Sequence[Mapping[str, object]]


@dataclass(frozen=True)
class _GraphReady:
    graph: ImportGraph
    module_files: dict[str, str]
    roots: tuple[RootPackage, ...]
    root_names: list[str]
    host: _HostConfig | None
    session_options: dict[str, object]


@dataclass(frozen=True)
class _Report:
    rule_id: str
    contract_name: str
    module_files: dict[str, str]
    selected: set[str]
    skip_importers_under: frozenset[str]


def run(
    files: list[str],
    repo_root: Path,
    config: AnalyzerConfig,
    executor: object | None = None,
) -> AnalyzerRunResult:
    _ = config, executor
    ready = _prepare_graph(files, repo_root)
    if isinstance(ready, AnalyzerRunResult):
        return ready
    return _collect_findings(ready, files, repo_root)


def _prepare_graph(files: list[str], repo_root: Path) -> _GraphReady | AnalyzerRunResult:
    if not any(Path(path).suffix in PYTHON_SOURCE_SUFFIXES for path in files):
        return AnalyzerRunResult()
    _ensure_configured()
    roots = discover_root_packages(repo_root)
    host = _read_host(repo_root)
    root_names = _root_names(roots, host)
    if not root_names:
        return AnalyzerRunResult()
    return _build_ready(repo_root, roots, root_names, host)


def _root_names(
    roots: tuple[RootPackage, ...], host: _HostConfig | None
) -> list[str]:
    names = [root.name for root in roots]
    if host is None:
        return names
    extra = host.session_options.get("root_packages", [])
    if not isinstance(extra, list | tuple):
        return names
    for name in extra:
        text = str(name)
        if text not in names:
            names.append(text)
    return names


def _build_ready(
    repo_root: Path,
    roots: tuple[RootPackage, ...],
    root_names: list[str],
    host: _HostConfig | None,
) -> _GraphReady | AnalyzerRunResult:
    include_external = needs_external_packages(roots) or _host_wants_external(host)
    inserted = _prepend_package_parents(roots)
    try:
        with _isolated_modules(root_names):
            graph = _build_graph(root_names, include_external)
            module_files = _module_files(graph.modules, repo_root)
    except Exception as exc:  # noqa: BLE001 - graph failures stay on this analyzer.
        return AnalyzerRunResult(
            errors=(f"import-boundaries failed to build the import graph: {exc}",)
        )
    finally:
        _restore_sys_path(inserted)
    session_options: dict[str, object] = {
        "root_packages": root_names,
        "include_external_packages": "true" if include_external else "false",
        "exclude_type_checking_imports": "true",
    }
    return _GraphReady(graph, module_files, roots, root_names, host, session_options)


def _collect_findings(
    ready: _GraphReady, files: list[str], repo_root: Path
) -> AnalyzerRunResult:
    _register_contracts(ready.host)
    planned = plan_contracts(
        ContractSources(
            ready.graph,
            ready.roots,
            ready.module_files,
            repo_root,
            ready.session_options,
        )
    )
    if ready.host is not None:
        planned.extend(_host_contracts(ready.host))
    selected = _selected_paths(files, repo_root)
    findings: list[Finding] = []
    errors: list[str] = []
    for item in planned:
        item_findings, item_errors = _check_contract(
            item, ready.graph, ready.module_files, selected
        )
        findings.extend(item_findings)
        errors.extend(item_errors)
    return AnalyzerRunResult(findings=tuple(_dedupe(findings)), errors=tuple(errors))


def _ensure_configured() -> None:
    from importlinter.configuration import configure  # noqa: PLC0415

    configure()


def _build_graph(root_names: list[str], include_external: bool) -> ImportGraph:
    from importlinter.application.app_config import settings  # noqa: PLC0415

    return settings.GRAPH_BUILDER.build(
        root_package_names=root_names,
        include_external_packages=include_external,
        exclude_type_checking_imports=True,
        cache_dir=None,
    )


def _register_contracts(host: _HostConfig | None) -> None:
    from importlinter.application.use_cases import (  # noqa: PLC0415
        _get_built_in_contract_types,
        _get_plugin_contract_types,
    )
    from importlinter.domain.contract import registry  # noqa: PLC0415

    for name, contract_class in _get_built_in_contract_types():
        registry.register(contract_class, name)
    if host is not None:
        for name, contract_class in _get_plugin_contract_types(host):
            registry.register(contract_class, name)


def _read_host(repo_root: Path) -> _HostConfig | None:
    from importlinter.application.use_cases import read_user_options  # noqa: PLC0415

    for name in ("pyproject.toml", "setup.cfg", ".importlinter"):
        path = repo_root / name
        if not path.is_file():
            continue
        try:
            options = read_user_options(config_filename=str(path))
        except FileNotFoundError:
            continue
        if options is not None and options.contracts_options:
            return options
    return None


def _host_wants_external(host: _HostConfig | None) -> bool:
    if host is None:
        return False
    raw = getattr(host, "session_options", {}).get("include_external_packages", "false")
    return str(raw).lower() == "true"


def _host_contracts(host: _HostConfig) -> list[PlannedContract]:
    planned: list[PlannedContract] = []
    session = host.session_options
    for options in host.contracts_options:
        contract_type = str(options.get("type", "host"))
        rule_id = RULES.get(contract_type)
        if rule_id is None:
            slug = contract_type.replace("_", "-")
            rule_id = f"import-boundaries.host.{slug}"
        planned.append(
            PlannedContract(dict(options), rule_id, session_options=dict(session))
        )
    return planned


def _prepend_package_parents(roots: Iterable[RootPackage]) -> list[str]:
    inserted: list[str] = []
    seen: set[str] = set()
    for root in roots:
        parent = str(root.directory.parent)
        if parent in seen:
            continue
        seen.add(parent)
        if parent in sys.path:
            continue
        sys.path.insert(0, parent)
        inserted.append(parent)
    return inserted


@contextmanager
def _isolated_modules(root_names: list[str]) -> Iterator[None]:
    saved: dict[str, ModuleType] = {}
    for key in list(sys.modules):
        if _belongs_to_root(key, root_names):
            saved[key] = sys.modules.pop(key)
    importlib.invalidate_caches()
    try:
        yield
    finally:
        for key in list(sys.modules):
            if _belongs_to_root(key, root_names):
                sys.modules.pop(key, None)
        sys.modules.update(saved)
        importlib.invalidate_caches()


def _belongs_to_root(module_name: str, root_names: list[str]) -> bool:
    return any(
        module_name == root or module_name.startswith(root + ".") for root in root_names
    )


def _restore_sys_path(inserted: list[str]) -> None:
    for parent in inserted:
        if parent in sys.path:
            sys.path.remove(parent)


def _module_files(modules: Iterable[str], repo_root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    root = repo_root.resolve()
    for name in modules:
        spec = importlib.util.find_spec(name)
        origin = getattr(spec, "origin", None) if spec is not None else None
        if not origin:
            continue
        path = Path(origin)
        try:
            relative = path.resolve().relative_to(root)
        except ValueError:
            continue
        files[name] = relative.as_posix()
    return files


def _selected_paths(files: list[str], repo_root: Path) -> set[str]:
    selected: set[str] = set()
    for file in files:
        path = Path(file)
        if path.is_absolute():
            try:
                path = path.resolve().relative_to(repo_root.resolve())
            except ValueError:
                selected.add(Path(file).as_posix())
                continue
        selected.add(path.as_posix())
    return selected


def _check_contract(
    planned: PlannedContract,
    graph: ImportGraph,
    module_files: dict[str, str],
    selected: set[str],
) -> tuple[list[Finding], list[str]]:
    from importlinter.domain.contract import (  # noqa: PLC0415
        InvalidContractOptions,
        registry,
    )

    options = planned.options
    name = str(options.get("name") or options.get("type") or "contract")
    contract_type = str(options.get("type", ""))
    failure: str | None = None
    try:
        contract_class = registry.get_contract_class(contract_type)
        contract = contract_class(
            name=name,
            session_options=planned.session_options or {},
            contract_options=options,
        )
        check = contract.check(deepcopy(graph), verbose=False)
    except InvalidContractOptions as exc:
        failure = _contract_error(name, exc)
    except Exception as exc:  # noqa: BLE001 - one bad contract must not stop the rest.
        failure = f"import-boundaries contract {name!r} failed: {exc}"
    if failure is not None:
        return [], [failure]
    if check.kept:
        return [], []
    report = _Report(
        planned.rule_id,
        name,
        module_files,
        selected,
        planned.skip_importers_under,
    )
    return _findings_from_metadata(contract_type, check.metadata, report, graph), []


def _contract_error(name: str, exc: object) -> str:
    errors = getattr(exc, "errors", None)
    if isinstance(errors, dict) and errors:
        detail = "; ".join(f"{key}: {value}" for key, value in errors.items())
        return f"import-boundaries invalid contract {name!r}: {detail}"
    return f"import-boundaries invalid contract {name!r}: {exc}"


def _findings_from_metadata(
    contract_type: str,
    metadata: dict,
    report: _Report,
    graph: ImportGraph,
) -> list[Finding]:
    if contract_type == "layers":
        return _layer_findings(metadata, report)
    findings: list[Finding] = []
    for links in _chains_for(contract_type, metadata, graph):
        findings.extend(_findings_for_chain(links, report))
    return findings


def _chains_for(
    contract_type: str, metadata: dict, graph: ImportGraph
) -> list[list[dict[str, object]]]:
    chains: list[list[dict[str, object]]] = []
    if contract_type == "acyclic_siblings":
        chains = _acyclic_chains(metadata, graph)
    elif contract_type == "forbidden":
        chains = _grouped_chains(metadata, "invalid_chains", "chains")
    elif contract_type == "independence":
        chains = _grouped_link_chains(metadata, "invalid_chains", "chains")
    elif contract_type == "protected":
        chains = _protected_chains(metadata)
    return chains


def _layer_findings(metadata: dict, report: _Report) -> list[Finding]:
    findings: list[Finding] = []
    for links in _grouped_link_chains(metadata, "invalid_dependencies", "routes"):
        findings.extend(_findings_for_chain(links, report))
    findings.extend(_undeclared_layer_findings(metadata, report))
    return findings


def _undeclared_layer_findings(metadata: dict, report: _Report) -> list[Finding]:
    findings: list[Finding] = []
    for module in sorted(metadata.get("undeclared_modules", ())):
        path = report.module_files.get(module)
        if path is None or path not in report.selected:
            continue
        findings.append(
            Finding(
                path=path,
                line=1,
                rule_id=report.rule_id,
                message=f"{report.contract_name}: {module} is not listed as a layer",
            )
        )
    return findings


def _grouped_chains(
    metadata: dict, group_key: str, chain_key: str
) -> list[list[dict[str, object]]]:
    return [
        list(chain)
        for group in metadata.get(group_key, [])
        for chain in group.get(chain_key, [])
    ]


def _grouped_link_chains(
    metadata: dict, group_key: str, chain_key: str
) -> list[list[dict[str, object]]]:
    return [
        list(detailed["chain"])
        for group in metadata.get(group_key, [])
        for detailed in group.get(chain_key, [])
    ]


def _protected_chains(metadata: dict) -> list[list[dict[str, object]]]:
    return [
        [link] for group in metadata.get("illegal_imports", []) for link in group.illegal_links
    ]


def _acyclic_chains(metadata: dict, graph: ImportGraph) -> list[list[dict[str, object]]]:
    grouped = metadata.get("cycle_breakers_by_package", {})
    return [links for pairs in grouped.values() if (links := _cycle_links(pairs, graph))]


def _cycle_links(pairs, graph: ImportGraph) -> list[dict[str, object]]:
    links: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for importer, imported in pairs:
        _add_cycle_pair(links, seen, graph, (importer, imported))
        _add_cycle_pair(links, seen, graph, (imported, importer))
    return links


def _add_cycle_pair(
    links: list[dict[str, object]],
    seen: set[tuple[str, str]],
    graph: ImportGraph,
    pair: tuple[str, str],
) -> None:
    if pair in seen:
        return
    importer, imported = pair
    details = graph.get_import_details(importer=importer, imported=imported)
    if not details:
        return
    seen.add(pair)
    links.append(
        {
            "importer": importer,
            "imported": imported,
            "line_numbers": tuple(item["line_number"] for item in details),
        }
    )


def _findings_for_chain(
    links: list[dict[str, object]], report: _Report
) -> list[Finding]:
    visible = [
        link
        for link in links
        if not _skipped_importer(str(link["importer"]), report.skip_importers_under)
    ]
    if not visible:
        return []
    message = f"{report.contract_name}: " + " -> ".join(
        _format_link(link) for link in links
    )
    findings: list[Finding] = []
    for link in visible:
        importer = str(link["importer"])
        path = report.module_files.get(importer)
        if path is None or path not in report.selected:
            continue
        findings.append(
            Finding(
                path=path,
                line=_first_line(link),
                rule_id=report.rule_id,
                message=message,
            )
        )
    return findings


def _skipped_importer(importer: str, prefixes: frozenset[str]) -> bool:
    return any(
        importer == prefix or importer.startswith(prefix + ".") for prefix in prefixes
    )


def _format_link(link: dict[str, object]) -> str:
    importer = link["importer"]
    imported = link["imported"]
    numbers = [str(number) for number in _line_numbers(link)]
    if numbers:
        return f"{importer} -> {imported} (line {', '.join(numbers)})"
    return f"{importer} -> {imported}"


def _first_line(link: dict[str, object]) -> int:
    numbers = _line_numbers(link)
    if numbers:
        return numbers[0]
    return 1


def _line_numbers(link: dict[str, object]) -> list[int]:
    raw = link.get("line_numbers") or ()
    if not isinstance(raw, tuple | list):
        return []
    return [number for number in raw if isinstance(number, int) and number > 0]


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple[str, int, str, str]] = set()
    unique: list[Finding] = []
    for finding in findings:
        key = (finding.path, finding.line, finding.rule_id, finding.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique
