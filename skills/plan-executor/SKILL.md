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
5. Destructive operations (`checkpoint-restore`) require explicit engineer confirmation. Every restore the executor makes passes `--exec-dir <exec_dir>`; otherwise the next `unit-begin` reports the restore itself as `foreign-changes`.
6. A gate cannot pass silently when checks are absent; no tests means escalation, not fake success.
7. A unit marked `**External:**` runs only when each of its `external` entries is `confirmed` (`run` in the settings, or a run-scope `consent`) or the engineer confirms it for that environment and access. `deny` stops the run; changes on prod are confirmed task by task, never for the whole run. Never run a step on an environment the plan does not list, and never widen a permission to another environment or from read to write.
8. Work beyond the unit's text happens only with the engineer's consent and is recorded with `unit-finish … --note`.

## Tool

`<SKILL_DIR>` is the directory containing this `SKILL.md`. Python ≥ 3.8, stdlib only. Every command prints JSON; errors print `{"ok": false, "errors": [...]}` with exit `2` (input/filesystem) or `1` (contract violation).

```bash
T="python <SKILL_DIR>/scripts/executor_tool.py"
$T ledger-init <exec_dir|auto> <plan_path> --workdir <repo> [--whole] [--allow-dirty] [--accept-drift]
$T unit-begin  <exec_dir>
$T unit-finish <exec_dir> <unit_id> pass|fail [--error "<signature>"] [--note "<agreed deviation or External confirmation>"]...  # --note repeats: one note per entry
$T consent     <exec_dir> <env> read|write  # the engineer chose "the whole run"; refused for prod write and deny
$T run-diff    <exec_dir>                # what this run changed: baseline vs last unit snapshot
$T accept-changes <exec_dir> [--note "<why>"]   # the engineer keeps files changed outside the run
$T checkpoint-restore <repo> <sha> [--paths <file> ...] --exec-dir <exec_dir>   # only after engineer confirmation
$T checkpoint-prune <exec_dir>            # after the run, with confirmation
```

Other commands (`ledger-next`, `ledger-mark`, `ledger-status`, `parse-tasks`, …) are listed in [TOOLING.md](references/TOOLING.md); the loop does not need them.

## Workflow

1. **BOOTSTRAP** — `ledger-init auto …`: the ledger goes to `<repo parent>/.exec/<repo>-<plan>/`, outside the repository and stable across sessions (a temp directory is refused as `exec-dir-ephemeral`). Tell the engineer the `exec_dir` from the result in one line before the first unit. Show the result's `warnings`. Stop and ask the engineer on these errors: `no-units`, `dirty-worktree`, `plan-drift`, `settings-drift`, `settings-unavailable`, `exec-dir-inside-workdir`. Details: [INPUT-DETECTION.md](references/INPUT-DETECTION.md).
2. **LOOP** — `unit-begin` → act on `reason`:

   | `reason` | Action |
   |---|---|
   | `ready`, `retry-available` | For every `external` entry: `confirmed` → one line, no question; otherwise ask (only this task / the whole run / stop; "the whole run" only for an entry with `access` and a known environment) or STOP on `deny` ([GATE.md](references/GATE.md)). Execute exactly this unit using `text` and `files` from the result (do not re-read the whole plan), then gate it with `strategy` ([EXECUTION-STRATEGY.md](references/EXECUTION-STRATEGY.md)) and call `unit-finish`. |
   | `in-progress` | A previous attempt was not finished: gate the current state and call `unit-finish`. |
   | `foreign-changes` | Files changed outside the run since the last unit (`foreign_changes`: `{path, status}`); nothing is marked running. Ask the engineer: accept / restore these files / stop ([GATE.md](references/GATE.md)). Without a confirmation channel, STOP with a stop-report listing the files. |
   | `exhausted`, `stagnated`, `blocked` | STOP with a stop-report. |
   | `all-done` | Go to FINALIZE. |

   `unit-finish … pass` snapshots and marks done (a failed snapshot turns into `fail`). `unit-finish … fail` returns `decision` (`retry`/`stop`) and `restore_to`; ask the engineer before `checkpoint-restore <repo> <restore_to> --exec-dir <exec_dir>`, then loop. Both move the ledger's `expected_tree`, so a retry is not reported as foreign. `foreign_changes: null` means the check is off (no git, or a ledger from before the check, where it starts after the next finished unit): show `foreign_warning` to the engineer in one line and continue.
3. **FINALIZE** — show `run-diff` (the run's own changes, separate from work that was uncommitted before), append out-of-scope findings to `BACKLOG.md` and `<plan base>-followups.json` (WORKFLOW.md, FINALIZE), propose `plan-resolver` per [RESOLVER-PROPOSAL.md](references/RESOLVER-PROPOSAL.md); offer `checkpoint-prune`.

Units of one `parallel_group` may run in any order, but always one at a time in one session.

## Language

**Dialogue language.** Everything the user sees is in the language of the primary task (the
goal, idea or findings in `plan-brainstorming`, the plan in every later skill): questions, option
labels and option descriptions in a question UI, status lines, confirmations, human gates, final
summaries and stop reports. Only tokens that parsers match stay in English: `### Task N:`,
`**Files:**`, `> Tier:`, command names and JSON field names. Sample phrases quoted in these
instructions ("Spec written to …", "MAX review passes done …", "I'm using the plan-writing
skill …") are templates: say them in the dialogue language, not verbatim. The language is
detected, not guessed: `ru` when more than 5% of the letters are Cyrillic, otherwise `en`.

In this skill: `executor_tool.py detect-lang <plan>`; the stop reports below use the same language.

## Stop Reports

Use [stop-report.en.md](assets/stop-report.en.md) or [stop-report.ru.md](assets/stop-report.ru.md) according to `executor_tool.py detect-lang <plan>` (`ru` when more than 5% of the plan's letters are Cyrillic, otherwise `en`). Put `git diff --stat` and at most ~80 lines of diff into the report, not the full diff.
