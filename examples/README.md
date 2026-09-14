# Examples

Copy these into **your** project after you install pyslop as a dependency. They are not this repository's own gates, and `pyslop init` does not write them.

```bash
uv add "pyslop[analyzers] @ git+https://github.com/snap-labs-ai/pyslop.git"
```

## Gates

| Surface | Copy from | Command | Analyzer stage |
| --- | --- | --- | --- |
| Local hook | [`.pre-commit-config.yaml`](.pre-commit-config.yaml) → your repo-root `.pre-commit-config.yaml` | `pyslop run --strict` (paths from pre-commit) | default (`always` + `pre-commit`) |
| CI whole repo | [`ci.yaml`](ci.yaml) job `pyslop-all` | `pyslop run --all --stage ci --strict` | adds CI-only analyzers (pylint) |
| CI changed files | [`ci.yaml`](ci.yaml) job `pyslop-changed` | `pyslop run --stage ci --strict --base origin/<base>` | same, limited to `base...HEAD` plus uncommitted |

Copy [`ci.yaml`](ci.yaml) to `.github/workflows/ci.yaml` and keep the job that matches your gate (or both). `pre-commit` is a tool in your repo (`uvx pre-commit install`). It is not a pyslop install extra.

After copying the hook file:

```bash
uvx pre-commit install
```

Without uv, set the hook `entry` to `pyslop run --strict` and put `pyslop` on `PATH`.

## detect-shims extension

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
