---
name: plan-executor
description: Use when executing a ready implementation plan, staged roadmap, or whole-plan task list that must advance one unit at a time with ledger-backed progress, gates, retries, rollback snapshots, and a final resolver proposal.
---

# plan-executor

## When to use

Use this skill when the plan already exists and the job is execution, not planning: staged plans from `plan-splitter`, plans from `plan-writing` (`### Task N:` headings), or other plans with explicit task headings.

Do not use it to invent a plan. Use `plan-writing` or `plan-splitter` first when the input is still unstructured.

## Hard Invariants

1. Never edit source `*.md` plan or stage files while executing them.
2. Progress lives only in `state.json`, changed only through `scripts/executor_tool.py`; `progress.md` is generated.
3. Exactly one unit runs at a time. A failed unit is retried or stops the run before anything else runs.
4. Nothing is committed to the user's branch: snapshots live in hidden refs `refs/plan-executor/<run>/<unit>`. The final commit is the engineer's.
5. Destructive operations (`checkpoint-restore`) require explicit engineer confirmation.
6. A gate cannot pass silently when checks are absent; no tests means escalation, not fake success.

## Tool

`<SKILL_DIR>` is the directory containing this `SKILL.md`. Python ≥ 3.8, stdlib only. Every command prints JSON; errors print `{"ok": false, "errors": [...]}` with exit `2` (input/filesystem) or `1` (contract violation).

```bash
T="python <SKILL_DIR>/scripts/executor_tool.py"
$T ledger-init <exec_dir> <plan_path> --workdir <repo> [--whole] [--allow-dirty] [--accept-drift]
$T unit-begin  <exec_dir>
$T unit-finish <exec_dir> <unit_id> pass|fail [--error "<signature>"]
$T checkpoint-restore <repo> <sha>        # only after engineer confirmation
$T checkpoint-prune <exec_dir>            # after the run, with confirmation
```

Other commands (`ledger-next`, `ledger-mark`, `ledger-status`, `parse-tasks`, …) are listed in [TOOLING.md](references/TOOLING.md); the loop does not need them.

## Workflow

1. **BOOTSTRAP** — `ledger-init`. `exec_dir` must be outside `<repo>` (or git-ignored). Stop and ask the engineer on these errors: `no-units`, `dirty-worktree`, `plan-drift`, `exec-dir-inside-workdir`. Details: [INPUT-DETECTION.md](references/INPUT-DETECTION.md).
2. **LOOP** — `unit-begin` → act on `reason`:

   | `reason` | Action |
   |---|---|
   | `ready`, `retry-available` | Execute exactly this unit using `text` and `files` from the result (do not re-read the whole plan), then gate it ([GATE.md](references/GATE.md)) with `strategy` ([EXECUTION-STRATEGY.md](references/EXECUTION-STRATEGY.md)) and call `unit-finish`. |
   | `in-progress` | A previous attempt was not finished: gate the current state and call `unit-finish`. |
   | `exhausted`, `stagnated`, `blocked` | STOP with a stop-report. |
   | `all-done` | Go to FINALIZE. |

   `unit-finish … pass` snapshots and marks done (a failed snapshot turns into `fail`). `unit-finish … fail` returns `decision` (`retry`/`stop`) and `restore_to`; ask the engineer before `checkpoint-restore <repo> <restore_to>`, then loop.
3. **FINALIZE** — propose `plan-resolver` per [RESOLVER-PROPOSAL.md](references/RESOLVER-PROPOSAL.md); offer `checkpoint-prune`.

Units of one `parallel_group` may run in any order, but always one at a time in one session.

## Stop Reports

Use [stop-report.en.md](assets/stop-report.en.md) or [stop-report.ru.md](assets/stop-report.ru.md) according to `executor_tool.py detect-lang <plan>` (`ru` when more than 5% of the plan's letters are Cyrillic, otherwise `en`). Put `git diff --stat` and at most ~80 lines of diff into the report, not the full diff.
