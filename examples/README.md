# Consumer snapshot

`examples/pyslop_extensions/detect_shims/` is what `pyslop extensions detect-shims` writes into a host repo. The packaged copy under `pyslop/templates/defaults/pyslop_extensions/detect_shims` is the source of truth.

Register it in the host `pyslop.toml`:

```toml
[[analyzers.extensions]]
id = "detect-shims"
entry-point = "pyslop_extensions/detect_shims/analyzer.py:analyze"
rules = "pyslop_extensions/detect_shims/rules.toml"
stage = "always"
inputs = "filenames"
```

See [docs/extensions.md](../docs/extensions.md).
