# Spec Delta

## Purpose

Reports illegal imports between Python modules so an agent can fix architecture residue from generated code without maintaining a contract file.

## ADDED Requirements

### Requirement: Default run includes boundary checks
The system SHALL run import boundary checks on a default analysis, with no stage flag required. The analyzer id SHALL be `import-boundaries`.

#### Scenario: Default analysis
- **WHEN** the user runs analysis with no stage flag and a selected file contains an illegal import
- **THEN** the finding is present in the result

#### Scenario: Analyzer list
- **WHEN** the user lists analyzers and boundary checking is available
- **THEN** the list includes `import-boundaries`

### Requirement: Missing checker is a skip
The system SHALL skip `import-boundaries` when its checker is not installed, using the same not-on-PATH skip as other optional analyzers, and SHALL still complete analysis.

#### Scenario: Checker absent
- **WHEN** the checker executable is not on PATH
- **THEN** analysis succeeds, `import-boundaries` is skipped, and no boundary findings are produced

### Requirement: Disable turns checks off
The system SHALL produce no boundary findings when `analyzers.disable` includes `import-boundaries`, and analysis SHALL still succeed.

#### Scenario: Analyzer disabled
- **WHEN** `import-boundaries` is disabled and a selected file contains an illegal import
- **THEN** analysis succeeds with no boundary findings

### Requirement: No importable package
The system SHALL produce no boundary findings and SHALL NOT fail the run when the tree has no importable root package.

#### Scenario: Loose scripts
- **WHEN** the selected tree contains Python files and no importable package
- **THEN** analysis succeeds with no boundary findings

### Requirement: Sibling cycles through two generations
The system SHALL report a dependency cycle among the direct children of each root package, and among the direct children of those children. It SHALL NOT report a cycle that exists only among deeper descendants. An import that is only evaluated to connect two siblings SHALL still count toward the higher cycle.

#### Scenario: Children import each other
- **WHEN** two direct children of a root package import each other
- **THEN** the selected file that contains one of those imports has an `import-boundaries.acyclic-siblings` finding

#### Scenario: Grandchildren import each other
- **WHEN** two direct children of a child package import each other
- **THEN** that cycle has an `import-boundaries.acyclic-siblings` finding

#### Scenario: Deeper cycle only
- **WHEN** a cycle exists only among modules nested more than two levels below the root and no higher sibling set cycles
- **THEN** there is no `import-boundaries.acyclic-siblings` finding

### Requirement: Generated trees are not sibling-checked
The system SHALL NOT check the children of a `migrations`, `tests`, `testing`, or `contrib` package as a sibling set.

#### Scenario: Migrations cycle
- **WHEN** two modules under a `migrations` package import each other and no higher sibling set cycles
- **THEN** there is no `import-boundaries.acyclic-siblings` finding

### Requirement: Feature siblings are independent
When a package has two or more direct children under `features`, `apps`, `plugins`, `slices`, `components`, or `bounded_contexts`, the system SHALL report any dependency between those children, including an indirect one. A module that is not one of those children MAY be imported by all of them.

#### Scenario: Cross-feature import
- **WHEN** `features.billing` imports `features.users`
- **THEN** the import site has an `import-boundaries.independence` finding

#### Scenario: Shared kernel
- **WHEN** two feature siblings both import `kernel` and `kernel` imports neither feature
- **THEN** there is no `import-boundaries.independence` finding

#### Scenario: Shared module reaches back
- **WHEN** `features.billing` imports `shared` and `shared` imports `features.users`
- **THEN** the chain has an `import-boundaries.independence` finding

#### Scenario: No convention directory
- **WHEN** sibling packages are not under one of those directory names
- **THEN** those siblings are not checked for independence

### Requirement: Hexagonal check turns on from package names
The system SHALL apply a hexagonal layer check to a package that contains at least one of `domain` or `core` and at least one of `api`, `cli`, `web`, `routes`, `presentation`, `interfaces`, `infrastructure`, `infra`, `adapters`, `db`, or `persistence`. It SHALL NOT apply that check to a package that contains both `apps.py` and `models.py`.

#### Scenario: Inner and outer names
- **WHEN** a package contains `domain` and `api` and does not contain both `apps.py` and `models.py`
- **THEN** the hexagonal layer check runs for that package

#### Scenario: Django-shaped package
- **WHEN** a package contains both `apps.py` and `models.py`
- **THEN** the hexagonal layer check does not run for that package

### Requirement: Layer direction is inward
Under an active hexagonal check, names that exist form outer, middle, then inner. Outer: `api`, `cli`, `web`, `routes`, `presentation`, `interfaces`, `infrastructure`, `infra`, `adapters`, `db`, `persistence`. Middle: `application`, `services`, `usecases`, `use_cases`, `commands`, `handlers`. Inner: `domain`, `core`. Outer modules MAY import each other. A middle or inner module MUST NOT import an outer module. An inner module MUST NOT import a middle module.

#### Scenario: Inner imports outer
- **WHEN** `domain` imports `api` in a package under the hexagonal check
- **THEN** the import site has an `import-boundaries.layers` finding

#### Scenario: Outer wires outer
- **WHEN** `api` and `infrastructure` both exist and `api` imports `infrastructure`
- **THEN** there is no `import-boundaries.layers` finding for that import

#### Scenario: Inner imports middle
- **WHEN** `domain` imports `services` under an active hexagonal check
- **THEN** the import site has an `import-boundaries.layers` finding

### Requirement: Absent tiers are omitted
A hexagonal tier name that is not in the package MUST NOT fail the layer check.

#### Scenario: Middle is absent
- **WHEN** `api` and `domain` exist and none of the middle names exist
- **THEN** the layer check runs and does not fail because the middle tier is absent

### Requirement: New siblings fail the layer check
Under an active hexagonal check, a sibling that is not a tier name and is not `migrations`, `tests`, or `conftest` MUST fail the check.

#### Scenario: Invented sibling
- **WHEN** a package under the hexagonal check contains a sibling named `helpers`
- **THEN** the layer check has an `import-boundaries.layers` finding

### Requirement: Production must not import tests
A non-test root package MUST NOT depend on `tests`, on a `tests` or `testing` package, or on `pytest` or `unittest`, directly or indirectly. Test code MAY import the root package.

#### Scenario: Application imports pytest
- **WHEN** a module in a non-test root package imports `pytest`
- **THEN** the import site has an `import-boundaries.forbidden` finding

#### Scenario: Tests import the application
- **WHEN** `tests` imports the root package and the root package does not depend on `tests`
- **THEN** there is no `import-boundaries.forbidden` finding for that import

### Requirement: Programs are not library imports
When `__main__`, `manage`, or `scripts` exists in a root package, other modules in that package MUST NOT import it. The program module MAY import the rest of the package. A `cli` package is not covered by this ban.

#### Scenario: Library imports __main__
- **WHEN** a library module imports the package `__main__`
- **THEN** the import site has an `import-boundaries.forbidden` finding

#### Scenario: Program imports the library
- **WHEN** `__main__` imports another module in the same package
- **THEN** there is no `import-boundaries.forbidden` finding for that import

### Requirement: Inner tier must not import SDKs
When the hexagonal layer check applies, `domain` and `core` MUST NOT depend on `fastapi`, `flask`, `django`, `starlette`, `sqlalchemy`, `boto3`, `requests`, `httpx`, `redis`, or `celery`, directly or indirectly, including through a re-export.

#### Scenario: Domain imports sqlalchemy
- **WHEN** `domain` imports `sqlalchemy` under an active hexagonal check
- **THEN** the import site has an `import-boundaries.forbidden` finding

#### Scenario: Hexagonal check inactive
- **WHEN** the hexagonal layer check does not apply
- **THEN** an import of `sqlalchemy` is not an `import-boundaries.forbidden` finding from this rule

### Requirement: Private packages stay inside their parent
A package whose name is `internal`, `impl`, `_impl`, or starts with `_` MUST NOT be imported from outside its parent package. The parent and the private package's descendants MAY import it.

#### Scenario: Cousin imports a private package
- **WHEN** `app.billing` imports `app.users._internal`
- **THEN** the import site has an `import-boundaries.protected` finding

#### Scenario: Parent imports its private package
- **WHEN** `app.users` imports `app.users._internal`
- **THEN** there is no `import-boundaries.protected` finding for that import

### Requirement: Migrations and conftest stay closed
A `migrations` package and a `conftest` module MUST NOT be imported from outside that package or module and its descendants.

#### Scenario: Application imports a migration
- **WHEN** `app.models` imports `app.migrations.versions.0001`
- **THEN** the import site has an `import-boundaries.protected` finding

### Requirement: SDKs stay in the outer tier
When the hexagonal layer check applies, `fastapi`, `flask`, `django`, `starlette`, `sqlalchemy`, `boto3`, `requests`, `httpx`, `redis`, and `celery` MUST NOT be imported from outside the outer-tier packages that exist in that package.

#### Scenario: Middle tier imports httpx
- **WHEN** a middle-tier module imports `httpx` under an active hexagonal check
- **THEN** the import site has an `import-boundaries.protected` finding

#### Scenario: Outer tier imports httpx
- **WHEN** an outer-tier module imports `httpx` under an active hexagonal check
- **THEN** there is no `import-boundaries.protected` finding for that import

### Requirement: Finding points at the import
Each violation SHALL be a finding on the file and line of an import statement. The rule id SHALL be one of `import-boundaries.acyclic-siblings`, `import-boundaries.independence`, `import-boundaries.layers`, `import-boundaries.forbidden`, or `import-boundaries.protected`. The fix hint SHALL tell the reader to remove or move the import and SHALL NOT recommend hiding it with a re-export, a pass-through, a lazy import, or a `TYPE_CHECKING` import.

#### Scenario: Direct illegal import
- **WHEN** a selected module imports a forbidden module on line 4
- **THEN** the finding path is that module, the line is 4, the rule id is one of the five ids, and the fix hint rejects hiding the import

### Requirement: Only selected import sites are reported
The system SHALL judge contracts against the whole package graph and SHALL emit a finding only for an import site in the selected file set. When an illegal chain includes edges outside that set, the finding message SHALL name those edges. A chain whose import sites are all outside the selected set SHALL produce no finding. Analysis of all files SHALL report violations anywhere in the package.

#### Scenario: New import completes an old chain
- **WHEN** the selected file imports `shared` and an unselected module `shared` imports another feature
- **THEN** the finding is on the selected import and the message names the unselected edge

#### Scenario: Untouched violation
- **WHEN** an illegal import exists only in files outside the selected set
- **THEN** there is no boundary finding

#### Scenario: All files
- **WHEN** the user analyzes all files and an unselected-by-diff module contains an illegal import
- **THEN** that import is a finding

### Requirement: Type-checking imports are ignored
An import that exists only so a type checker can see it MUST NOT count as a dependency for these contracts.

#### Scenario: Cycle only for typing
- **WHEN** two siblings import each other only under `TYPE_CHECKING`
- **THEN** there is no `import-boundaries.acyclic-siblings` finding

### Requirement: Host contracts are checked
When the host already defines import contracts, the system SHALL check those contracts as well. Each host violation SHALL be a finding on the import site with a rule id under `import-boundaries.` and a fix hint.

#### Scenario: Host forbids a module
- **WHEN** the host forbids `package.legacy` and a selected file imports it
- **THEN** that import is a finding in addition to any generated-contract findings

### Requirement: Select and ignore apply
Boundary findings SHALL be kept or dropped by the existing `select` and `ignore` patterns on rule ids.

#### Scenario: One contract ignored
- **WHEN** `ignore` includes `import-boundaries.layers` and both a layers violation and a forbidden violation are in the selected files
- **THEN** the layers finding is omitted and the forbidden finding remains
