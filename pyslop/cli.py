from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import click
import typer

from pyslop.axi import parse_finding_fields, render_error
from pyslop.runner import inspect_analyzers, run
from pyslop.scaffold import ScaffoldError, ScaffoldResult, scaffold, scaffold_extensions
from pyslop.types import RunOptions, RunResult

_RUN_RESULT_ERRORS_EXIT_CODE = 2
_INIT_TARGETS = ("cursor", "claude")

app = typer.Typer(
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=False,
    help="Unified Python static analysis for AI slop.",
)

FilesOption = Annotated[list[str] | None, typer.Option("--files")]
AllOption = Annotated[bool, typer.Option("--all")]
BaseOption = Annotated[str, typer.Option("--base", help="Git ref to diff against")]
UncommittedOption = Annotated[bool, typer.Option("--uncommitted-only")]
PathOption = Annotated[
    str, typer.Option("--path", help="Restrict git-diff mode to a path")
]
ConfigOption = Annotated[str | None, typer.Option("--config")]
FilesFromOption = Annotated[str | None, typer.Option("--files-from")]
StageOption = Annotated[
    str | None, typer.Option("--stage", help="Include CI-stage analyzers (value: ci)")
]
TimingsOption = Annotated[bool, typer.Option("--timings")]
NoCacheOption = Annotated[bool, typer.Option("--no-cache")]
NoExcludeOption = Annotated[bool, typer.Option("--no-exclude")]
FullOption = Annotated[bool, typer.Option("--full")]
StrictOption = Annotated[bool, typer.Option("--strict")]
FieldsOption = Annotated[str | None, typer.Option("--fields")]


def _system_exit_return_code(exc: SystemExit) -> int:
    code = exc.code
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    if isinstance(code, str):
        return int(code)
    raise TypeError(
        "int() argument must be a string, a bytes-like object or a real number, "
        f"not '{type(code).__name__}'"
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = app(
            args=list(argv) if argv is not None else None, standalone_mode=False
        )
    except ScaffoldError as exc:
        print(render_error(str(exc), "pyslop init --help"), end="")
        result = _RUN_RESULT_ERRORS_EXIT_CODE
    except click.exceptions.UsageError as exc:
        print(
            render_error(exc.format_message(), "pyslop run --help"),
            end="",
        )
        result = _RUN_RESULT_ERRORS_EXIT_CODE
    except click.exceptions.Exit as exc:
        result = int(exc.exit_code)
    except click.ClickException as exc:
        print(
            render_error(exc.format_message(), "pyslop run --help"),
            end="",
        )
        result = _RUN_RESULT_ERRORS_EXIT_CODE
    except SystemExit as exc:
        result = _system_exit_return_code(exc)
    else:
        result = result if isinstance(result, int) else 0
    return result


def _analysis_options(
    base: str,
    uncommitted_only: bool,
    path: str,
    files: list[str] | None,
    all_files: bool,
    config: str | None,
    files_from: str | None,
    stage: str | None,
    timings: bool,
    no_cache: bool,
    no_exclude: bool,
    full: bool,
    strict: bool,
    fields: str | None,
) -> RunOptions:
    if stage not in (None, "ci"):
        print(render_error("--stage must be ci", "pyslop run --help"), end="")
        raise typer.Exit(code=_RUN_RESULT_ERRORS_EXIT_CODE)
    try:
        parsed_fields = parse_finding_fields(fields)
    except ValueError as exc:
        print(render_error(str(exc), "pyslop run --help"), end="")
        raise typer.Exit(code=_RUN_RESULT_ERRORS_EXIT_CODE) from exc
    file_list = list(files) if files else []
    return RunOptions(
        repo_root=Path.cwd(),
        base=base or "main",
        uncommitted_only=uncommitted_only,
        path=path or "",
        files=tuple(file_list) if file_list else None,
        all_files=all_files,
        config_path=config,
        no_exclude=no_exclude,
        stage=stage,
        files_from=files_from,
        timings=timings or _env_timings_enabled(),
        no_cache=no_cache,
        full=full,
        strict=strict,
        fields=parsed_fields,
    )


def _exit_analysis(kind: str, options: RunOptions) -> None:
    if kind == "analyzers":
        raise typer.Exit(code=_inspect_analyzers_command(options))
    raise typer.Exit(code=_run_analysis_command(options))


def _register_analysis(kind: str) -> None:
    def command(
        ctx: typer.Context,
        base: BaseOption = "main",
        uncommitted_only: UncommittedOption = False,
        path: PathOption = "",
        files: FilesOption = None,
        all_files: AllOption = False,
        config: ConfigOption = None,
        files_from: FilesFromOption = None,
        stage: StageOption = None,
        timings: TimingsOption = False,
        no_cache: NoCacheOption = False,
        no_exclude: NoExcludeOption = False,
        full: FullOption = False,
        strict: StrictOption = False,
        fields: FieldsOption = None,
    ) -> None:
        if kind == "callback" and ctx.invoked_subcommand is not None:
            return
        target = "analyzers" if kind == "analyzers" else "run"
        _exit_analysis(
            target,
            _analysis_options(
                base,
                uncommitted_only,
                path,
                files,
                all_files,
                config,
                files_from,
                stage,
                timings,
                no_cache,
                no_exclude,
                full,
                strict,
                fields,
            ),
        )

    names = {
        "callback": "default_callback",
        "run": "run",
        "analyzers": "analyzers",
    }
    command.__name__ = names[kind]
    if kind == "callback":
        app.callback(invoke_without_command=True)(command)
        return
    app.command(names[kind])(command)


_register_analysis("callback")
_register_analysis("run")
_register_analysis("analyzers")


@app.command()
def init(
    target: Annotated[str | None, typer.Argument()] = None,
    extensions: Annotated[list[str] | None, typer.Option("--extensions")] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    if target not in (None, *_INIT_TARGETS):
        print(
            render_error(
                f"init target must be {' or '.join(_INIT_TARGETS)}",
                "pyslop init --help",
            ),
            end="",
        )
        raise typer.Exit(code=_RUN_RESULT_ERRORS_EXIT_CODE)
    repo_root = Path.cwd()
    if extensions is not None:
        raise typer.Exit(
            code=_handle_init_and_extensions_command(
                target, extensions, overwrite, repo_root
            )
        )
    raise typer.Exit(code=_handle_init_command(target, overwrite, repo_root))


@app.command()
def extensions(
    names: Annotated[list[str] | None, typer.Argument()] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    raise typer.Exit(code=_handle_extensions_command(names, overwrite, Path.cwd()))


def _handle_init_command(
    init_target: str | None,
    overwrite: bool,
    repo_root: Path,
) -> int:
    scaffold_result = scaffold(
        repo_root,
        init_target or None,
        overwrite=overwrite,
    )
    _print_scaffold_feedback(scaffold_result, repo_root, "init")
    return 0


def _handle_init_and_extensions_command(
    init_target: str | None,
    extension_names: Sequence[str] | None,
    overwrite: bool,
    repo_root: Path,
) -> int:
    init_result = scaffold(repo_root, init_target or None, overwrite=overwrite)
    extension_result = scaffold_extensions(
        repo_root, tuple(extension_names or ()), overwrite=overwrite
    )
    combined = ScaffoldResult(created=init_result.created + extension_result.created)
    _print_scaffold_feedback(combined, repo_root, "init")
    return 0


def _handle_extensions_command(
    extension_names: Sequence[str] | None, overwrite: bool, repo_root: Path
) -> int:
    result = scaffold_extensions(
        repo_root, tuple(extension_names or ()), overwrite=overwrite
    )
    _print_scaffold_feedback(result, repo_root, "extensions")
    return 0


def _run_analysis_command(run_options: RunOptions) -> int:
    result = run(run_options)
    _print_run_feedback(result)
    return result.exit_code


def _inspect_analyzers_command(run_options: RunOptions) -> int:
    result = inspect_analyzers(run_options)
    _print_run_feedback(result)
    return result.exit_code


def _print_run_feedback(result: RunResult) -> None:
    if result.timings_text:
        print(result.timings_text, file=sys.stderr)
    if result.stdout_text:
        print(result.stdout_text, end="")


def _print_scaffold_feedback(
    result: ScaffoldResult, repo_root: Path, command_name: str
) -> None:
    if not result.created:
        print(f"pyslop: {command_name} completed. No files created (already exists).")
        return
    print(f"pyslop: {command_name} completed. Created {len(result.created)} files:")
    for path in result.created:
        print(f"- {path.relative_to(repo_root).as_posix()}")


def _env_timings_enabled() -> bool:
    return os.environ.get("PYSLOP_TIMINGS") == "1"


if __name__ == "__main__":
    raise SystemExit(main())
