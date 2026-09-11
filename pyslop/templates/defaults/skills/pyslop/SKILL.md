---
name: pyslop
description: Removes AI-generated code slop and code smells. Use when reviewing branch changes for cleanup before shipping.
---

# Remove AI code slop

Check the diff against main and remove or refactor AI-generated slop introduced in the branch.

## Workflow intent

The main agent orchestrates. It does not bulk-fix files itself.

- Run `pyslop run` (no `--strict`), read AXI stdout, delegate fixes, rerun, repeat.
- Stop when stdout reports `findings: 0 in this file set`.

## 1. Run analysis

```bash
pyslop run
```

Use the TOON table on stdout (`path`, `line`, `rule`, `fix`, `message`). Pass `--full` when a message is truncated. Run `pyslop analyzers` if tools were skipped. Filename-analyzer results cache under `.pyslop/cache/`; pass `--no-cache` to rescan. Index analyzers are not cached.

## 2. Delegate by file

- Create one sub-agent per `path` that still has findings.
- Pass the file path, that file’s findings, `fix` text, and these guardrails.
- Each sub-agent edits only its assigned file unless a finding requires a multi-file change.
- Review sub-agent edits and resolve conflicts.

## 3. Re-run

Re-run `pyslop run` after delegated changes. Repeat until stdout reports zero findings.

## Guardrails

- Keep behavior unchanged unless fixing a clear bug.
- Preserve existing architecture and naming patterns.
- Prefer small, deterministic refactors over broad rewrites.
