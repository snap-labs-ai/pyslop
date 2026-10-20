from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from grimp import ImportGraph

from pyslop.analyzers.import_boundaries.discover import RootPackage

OUTER = (
    "api",
    "cli",
    "web",
    "routes",
    "presentation",
    "interfaces",
    "infrastructure",
    "infra",
    "adapters",
    "db",
    "persistence",
)
MIDDLE = (
    "application",
    "services",
    "usecases",
    "use_cases",
    "commands",
    "handlers",
)
INNER = ("domain", "core")
CONVENTION_PARENTS = frozenset(
    {"features", "apps", "plugins", "slices", "components", "bounded_contexts"}
)
SKIP_LEAVES = frozenset({"migrations", "tests", "testing", "contrib"})
ENTRY_LEAVES = frozenset({"__main__", "manage", "scripts"})
PRIVATE_LEAVES = frozenset({"internal", "impl", "_impl"})
CLOSED_LEAVES = frozenset({"migrations", "conftest"})
EXTERNAL_TESTS = ("pytest", "unittest")
SDKS = (
    "fastapi",
    "flask",
    "django",
    "starlette",
    "sqlalchemy",
    "boto3",
    "requests",
    "httpx",
    "redis",
    "celery",
)
RULES = {
    "acyclic_siblings": "import-boundaries.acyclic-siblings",
    "independence": "import-boundaries.independence",
    "layers": "import-boundaries.layers",
    "forbidden": "import-boundaries.forbidden",
    "protected": "import-boundaries.protected",
}
SDK_PROTECTED_NAME = "SDKs stay in the outer tier"
_MIN_GROUP = 2


def _visible_sdks(graph: ImportGraph) -> list[str]:
    modules = set(graph.modules)
    return [sdk for sdk in SDKS if sdk in modules]


@dataclass(frozen=True)
class PlannedContract:
    options: dict[str, object]
    rule_id: str
    session_options: dict[str, object] | None = None
    skip_importers_under: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ContractSources:
    graph: ImportGraph
    roots: tuple[RootPackage, ...]
    module_files: dict[str, str]
    repo_root: Path
    session_options: dict[str, object]


def plan_contracts(sources: ContractSources) -> list[PlannedContract]:
    graph = sources.graph
    roots = sources.roots
    module_files = sources.module_files
    repo_root = sources.repo_root
    session_options = sources.session_options
    root_names = {root.name for root in roots}
    non_test = [root.name for root in roots if not root.is_test]
    containers = _hexagonal_containers(graph, module_files, repo_root, root_names)
    planned: list[PlannedContract] = []
    planned.extend(_acyclic(graph, non_test, session_options))
    planned.extend(_independence(graph, root_names, session_options))
    planned.extend(_layers(graph, containers, session_options))
    planned.extend(_forbidden_tests(graph, non_test, root_names, session_options))
    planned.extend(_forbidden_programs(graph, non_test, session_options))
    planned.extend(_forbidden_sdks(graph, containers, session_options))
    planned.extend(_protected_private(graph, root_names, session_options))
    planned.extend(_protected_closed(graph, root_names, session_options))
    planned.extend(_protected_sdks(graph, containers, session_options))
    return planned


def needs_external_packages(roots: tuple[RootPackage, ...]) -> bool:
    if any(not root.is_test for root in roots):
        return True
    return bool(_filesystem_hexagonal(roots))


def _acyclic(
    graph: ImportGraph,
    non_test: list[str],
    session_options: dict[str, object],
) -> list[PlannedContract]:
    planned: list[PlannedContract] = []
    for root in non_test:
        if root not in graph.modules:
            continue
        skips = [
            module
            for module in _under(graph, root)
            if module != root and _leaf(module) in SKIP_LEAVES
        ]
        options: dict[str, object] = {
            "name": f"Acyclic siblings in {root}",
            "type": "acyclic_siblings",
            "ancestors": [root],
            "depth": "1",
        }
        if skips:
            options["skip_descendants"] = skips
        planned.append(
            PlannedContract(options, RULES["acyclic_siblings"], session_options)
        )
    return planned


def _independence(
    graph: ImportGraph,
    root_names: set[str],
    session_options: dict[str, object],
) -> list[PlannedContract]:
    planned: list[PlannedContract] = []
    for module in sorted(graph.modules):
        if not _in_roots(module, root_names):
            continue
        if _leaf(module) not in CONVENTION_PARENTS:
            continue
        children = sorted(graph.find_children(module))
        if len(children) < _MIN_GROUP:
            continue
        planned.append(
            PlannedContract(
                {
                    "name": f"Independent siblings in {module}",
                    "type": "independence",
                    "modules": children,
                },
                RULES["independence"],
                session_options,
            )
        )
    return planned


def _layers(
    graph: ImportGraph,
    containers: list[str],
    session_options: dict[str, object],
) -> list[PlannedContract]:
    planned: list[PlannedContract] = []
    for container in containers:
        tails = {_leaf(child): child for child in graph.find_children(container)}
        layers = [
            _tier_line([name for name in names if name in tails])
            for names in (OUTER, MIDDLE, INNER)
        ]
        layers = [line for line in layers if line]
        if len(layers) < _MIN_GROUP:
            continue
        planned.append(
            PlannedContract(
                {
                    "name": f"Hexagonal layers in {container}",
                    "type": "layers",
                    "containers": [container],
                    "layers": layers,
                    "exhaustive": "true",
                    "exhaustive_ignores": ["migrations", "tests", "conftest"],
                },
                RULES["layers"],
                session_options,
            )
        )
    return planned


def _forbidden_tests(
    graph: ImportGraph,
    non_test: list[str],
    root_names: set[str],
    session_options: dict[str, object],
) -> list[PlannedContract]:
    sources = [
        module
        for root in non_test
        for module in _under(graph, root)
        if not _is_test_module(module)
    ]
    if not sources:
        return []
    forbidden = [
        module
        for module in sorted(graph.modules)
        if _in_roots(module, root_names) and _is_test_module(module)
    ]
    forbidden.extend(EXTERNAL_TESTS)
    return [
        PlannedContract(
            {
                "name": "Production must not import tests",
                "type": "forbidden",
                "source_modules": sources,
                "forbidden_modules": forbidden,
                "as_packages": "false",
            },
            RULES["forbidden"],
            session_options,
        )
    ]


def _forbidden_programs(
    graph: ImportGraph,
    non_test: list[str],
    session_options: dict[str, object],
) -> list[PlannedContract]:
    planned: list[PlannedContract] = []
    for root in non_test:
        if root not in graph.modules:
            continue
        forbidden = [
            module
            for module in _under(graph, root)
            if _leaf(module) in ENTRY_LEAVES or _has_entry_ancestor(module, root)
        ]
        if not forbidden:
            continue
        forbidden_set = set(forbidden)
        sources = [
            module for module in _under(graph, root) if module not in forbidden_set
        ]
        if not sources:
            continue
        planned.append(
            PlannedContract(
                {
                    "name": f"Programs in {root} are not library imports",
                    "type": "forbidden",
                    "source_modules": sources,
                    "forbidden_modules": forbidden,
                    "as_packages": "false",
                },
                RULES["forbidden"],
                session_options,
            )
        )
    return planned


def _forbidden_sdks(
    graph: ImportGraph,
    containers: list[str],
    session_options: dict[str, object],
) -> list[PlannedContract]:
    sources = [
        f"{container}.{name}"
        for container in containers
        for name in INNER
        if f"{container}.{name}" in graph.modules
    ]
    if not sources:
        return []
    visible = _visible_sdks(graph)
    if not visible:
        return []
    return [
        PlannedContract(
            {
                "name": "Inner tier must not import SDKs",
                "type": "forbidden",
                "source_modules": sources,
                "forbidden_modules": visible,
                "as_packages": "true",
            },
            RULES["forbidden"],
            session_options,
        )
    ]


def _protected_private(
    graph: ImportGraph,
    root_names: set[str],
    session_options: dict[str, object],
) -> list[PlannedContract]:
    planned: list[PlannedContract] = []
    for module in sorted(graph.modules):
        if not _in_roots(module, root_names) or "." not in module:
            continue
        if not _is_private(_leaf(module)):
            continue
        parent = module.rsplit(".", 1)[0]
        planned.append(
            PlannedContract(
                {
                    "name": f"{module} stays inside {parent}",
                    "type": "protected",
                    "protected_modules": [module],
                    "allowed_importers": [parent],
                    "as_packages": "true",
                },
                RULES["protected"],
                session_options,
            )
        )
    return planned


def _protected_closed(
    graph: ImportGraph,
    root_names: set[str],
    session_options: dict[str, object],
) -> list[PlannedContract]:
    planned: list[PlannedContract] = []
    for module in sorted(graph.modules):
        if not _in_roots(module, root_names):
            continue
        if _leaf(module) not in CLOSED_LEAVES:
            continue
        planned.append(
            PlannedContract(
                {
                    "name": f"{module} stays closed",
                    "type": "protected",
                    "protected_modules": [module],
                    "allowed_importers": [],
                    "as_packages": "true",
                },
                RULES["protected"],
                session_options,
            )
        )
    return planned


def _protected_sdks(
    graph: ImportGraph,
    containers: list[str],
    session_options: dict[str, object],
) -> list[PlannedContract]:
    outers: list[str] = []
    inners: list[str] = []
    for container in containers:
        for child in graph.find_children(container):
            leaf = _leaf(child)
            if leaf in OUTER:
                outers.append(child)
            if leaf in INNER:
                inners.append(child)
    if not outers:
        return []
    visible = _visible_sdks(graph)
    if not visible:
        return []
    return [
        PlannedContract(
            {
                "name": SDK_PROTECTED_NAME,
                "type": "protected",
                "protected_modules": visible,
                "allowed_importers": outers,
                "as_packages": "true",
            },
            RULES["protected"],
            session_options,
            skip_importers_under=frozenset(inners),
        )
    ]


def _hexagonal_containers(
    graph: ImportGraph,
    module_files: dict[str, str],
    repo_root: Path,
    root_names: set[str],
) -> list[str]:
    containers: list[str] = []
    for module in sorted(graph.modules):
        if not _in_roots(module, root_names):
            continue
        tails = {_leaf(child) for child in graph.find_children(module)}
        if not (set(INNER) & tails and set(OUTER) & tails):
            continue
        relative = module_files.get(module)
        if relative is None:
            continue
        directory = (repo_root / relative).parent
        if (directory / "apps.py").is_file() and (directory / "models.py").is_file():
            continue
        containers.append(module)
    return containers


def _filesystem_hexagonal(roots: tuple[RootPackage, ...]) -> bool:
    for root in roots:
        if root.is_test:
            continue
        names = {
            child.name
            for child in root.directory.iterdir()
            if child.is_dir() or child.suffix == ".py"
        }
        bare = {name[:-3] if name.endswith(".py") else name for name in names}
        if (root.directory / "apps.py").is_file() and (
            root.directory / "models.py"
        ).is_file():
            continue
        if set(INNER) & bare and set(OUTER) & bare:
            return True
    return False


def _tier_line(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return " : ".join(names)


def _under(graph: ImportGraph, root: str) -> list[str]:
    if root not in graph.modules:
        return []
    return [root, *sorted(graph.find_descendants(root))]


def _in_roots(module: str, root_names: set[str]) -> bool:
    head = module.split(".", 1)[0]
    return head in root_names


def _leaf(module: str) -> str:
    return module.rsplit(".", 1)[-1]


def _is_test_module(module: str) -> bool:
    return any(part in {"tests", "testing"} for part in module.split("."))


def _is_private(leaf: str) -> bool:
    return leaf in PRIVATE_LEAVES or leaf.startswith("_")


def _has_entry_ancestor(module: str, root: str) -> bool:
    if not module.startswith(root + "."):
        return False
    parts = module[len(root) + 1 :].split(".")
    return any(part in ENTRY_LEAVES for part in parts[:-1])
