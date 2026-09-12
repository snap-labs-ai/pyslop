# Extension protocol v1

Install the bundled sample with:

```bash
pyslop extensions detect-shims
```

That copies the packaged detect-shims analyzer into `pyslop_extensions/detect_shims/` and appends it to `pyslop.toml`. It is an entry-point extension (not a command extension). A checked-in consumer snapshot lives in [`examples/pyslop_extensions/detect_shims`](../examples/pyslop_extensions/detect_shims).

## Command extensions

Pyslop starts the command **once** with the discovered file list as extra argv.

Stdout MUST be a JSON array of objects with:

- `path`
- `line`
- `rule_id`
- `message`

Exit code 2 or greater is a tool failure. Exit 1 may still include that JSON.

## Entry-point extensions

`entry-point` is `module:function` or a repo-relative `path.py:function`. The function receives `(files, repo_root, config_path)` and returns `list[Finding]`.

## Index extensions

Set `inputs = "index"` and `index-roots`. The process receives `PYSLOP_INDEX_ROOTS` (OS path separator). Findings outside the discovered file set are dropped.

## Trust

Command extensions run as a subprocess with the discovered paths on argv. Entry-point extensions import and call Python from the repo (`path.py:function` or `module:function`). Pyslop does not sandbox either form. Treat extension code as part of the trusted repository, the same as any other local script you execute.

