---
name: fix-code-slop
description: Drive `pyslop run` until the findings are empty. Use whenever the user wants to clean AI-generated Python slop, code smells, agent leftovers, placeholder comments, pass-through shims, or lint residue before a PR or ship — even if they only say "clean the branch", "fix slop", "fix-code-slop", "fix pyslop", "work the findings", or "make CI green" without naming this skill. Prefer this over ad-hoc ruff/mypy loops when pyslop is in the repo.
---

# Clear the pyslop findings

`pyslop` already chose the file set and ranked the residue. Your job is to make stdout say `findings: 0 in this file set` without turning that into a rewrite of the branch.

The orchestrating agent reads findings and delegates. It does not bulk-edit every listed file itself. Parallel per-file work is faster and keeps two agents from fighting over the same module.

## Loop

1. Run analysis (never `--strict` — that flag is a CI gate, not an agent loop):

```bash
pyslop run
```

Honor an explicit file set if the user gave one (`--files`, `--path`, `--base`, `--uncommitted-only`, `--all`). Default `pyslop run` diffs against `main` plus uncommitted files and needs a git work tree. If stdout is `error:`, recover with `--files` / `--all` or fix the git/config problem; do not invent findings.

2. Read stdout:
   - Done: `findings: 0 in this file set`.
   - Work: a `findings[N]{path,line,rule,fix,message}:` table. Group rows by `path`. `fix` is the intended change; `message` is why. If a message is truncated, rerun with `--full` for that pass.
   - If `skipped[...]` or `help:` mentions analyzers, run `pyslop analyzers` so you know which tools never ran. Filename-analyzer results cache under `.pyslop/cache/`; pass `--no-cache` only when a rescan is needed. Index analyzers are not cached.

3. One sub-agent per `path` that still has rows. Give it that file, those rows, and the guardrails below. It edits only its file unless a finding truly requires a multi-file change. Review edits and resolve conflicts.

4. Re-run the same `pyslop run` invocation. Repeat until the table is empty or a finding is a real product decision you should report instead of guessing.

## Why the edits stay small

Findings are residue and smell, not a license to redesign. Keep runtime behavior the same unless the row is a clear bug. Match the repo’s architecture and naming. Prefer a local, deterministic refactor over a broad rewrite — otherwise the next `pyslop run` will just surface a different pile of churn.
