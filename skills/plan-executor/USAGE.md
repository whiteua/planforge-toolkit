# plan-executor — Quick Reference

Execute a ready plan or staged roadmap one unit at a time with ledger-backed progress, gates, retries, and rollback snapshots that never touch your branch history.

## How to Invoke

In VS Code Copilot chat, type:

```
/plan-executor <plan-or-roadmap-path>
/plan-executor <plan-or-roadmap-path> commit     # after the audit: commit the run's result
```

### Usage Examples

```bash
# Execute a plan from plan-writing (### Task N: headings)
/plan-executor docs/plans/plan01-impl.md

# Execute a staged roadmap (stages in dependency order)
/plan-executor docs/plans/plan01-impl-roadmap.md

# A prose plan without task headings, as a single unit
/plan-executor docs/plans/notes.md --whole

# After plan-resolver: commit only the run's files and the audit's fixes (hooks run, no push)
/plan-executor docs/plans/plan01-impl.md commit
```

## Arguments

| Argument | Required | Description |
|---|---|---|
| Plan/Roadmap path | **Yes** | Plan `.md` with task headings, or a `-roadmap.md` from plan-splitter |
| `--whole` | No | Treat the plan as whole even if a roadmap exists; a plan without task headings becomes one unit |
| `commit` | No | Commit mode, a separate call after the audit: rebuilds the diff report with the audit's fixes and commits the run's files plus those fixes; asks before committing audit fixes |

## Input Types

| Input | Detection | Behavior |
|---|---|---|
| Staged roadmap (`-roadmap.md`) | Stage table + dependencies | Parts in dependency order; each part's text is its `<base>-<id>.md` (`a`, `b`, …) |
| Whole plan (`### Task N:` headings) | Task headings outside code blocks | Tasks strictly in order; `Phase`/`Step` headings do not become units when `Task` headings exist |

## What Happens

```
BOOTSTRAP:  ledger-init  → units, ledger, baseline snapshot; you are told where the ledger lives
LOOP:       unit-begin   → (external unit: asks you first) → execute the unit → gate → unit-finish
                           (pass: snapshot + done / fail: retry or stop)
FINALIZE:   <base>-diffs.md (what this run changed), findings → journal + BACKLOG.md + <goal>-followups.json, propose plan-resolver
COMMIT:     /plan-executor <plan> commit (after the audit) → diff report with the audit's fixes → commit-run → offer to prune snapshots
```

Per unit the agent calls the tool twice and reads only that unit's section and files, not the whole plan.

## Gates, Retries and Rollback

- A failed unit is retried before anything else runs; later tasks never run on top of a broken one
- 3 attempts per unit (1 primary + 2 retries); the same error signature twice → immediate STOP
- A gate cannot pass silently if tests are missing → escalation, not fake success
- Gate depth follows the plan tier, lowered for checkpoint tasks, documentation-only tasks (light) and test-only tasks (one step down)
- A task marked `**External:** <environment> (read|write)` runs without a question only when the spec allows that access for the whole run (`read=run` / `write=run`); otherwise you are asked: only this task / the whole run / stop ("the whole run" only when the task names `(read)` or `(write)` and the environment is in the settings). `deny` stops the run, changes on prod are confirmed task by task, and the executor never runs a step on an environment the plan does not list
- Work beyond a task's text (a defect the gate found) is done only with your consent and recorded as a note in the ledger
- Snapshots are stored in hidden git refs `refs/plan-executor/<run>/<unit>`: no commits on your branch during the run. Only the `commit` mode commits, after the audit: the run's files and the audit's fixes, with your hooks; never push, amend or force. Files you changed before the run that the run also changed are not committed (`mixed-files`)
- Rollback (`checkpoint-restore`) restores files to the last good snapshot and removes files created after it, or only the files you name — always after your confirmation

## Stop Conditions

| Condition | Action |
|---|---|
| All units done | Finalize → propose resolver |
| 3 attempts exhausted / same error twice | STOP with stop-report |
| Plan has no task headings (no `--whole`) | STOP: add headings, run plan-splitter, or use `--whole` |
| Uncommitted changes in the repo at start | Ask: commit/stash, or continue with them in the baseline |
| Plan file changed since the ledger was created | STOP and ask: new run, or accept the changed plan |
| Files changed outside the run between tasks (except `BACKLOG.md`) | Ask: accept them, restore these files, or stop; a silent run stops with the file list |

## Output

- `<exec_dir>/state.json` — ledger (source of truth for progress)
- `<exec_dir>/progress.md` — human-readable progress

- `BACKLOG.md` at the repository root — the same out-of-scope defects, appended to the plan's goal section (`/plan-brainstorming BACKLOG.md` starts the next cycle from them)
- `<plan base>-diffs.md` next to the plan — the diff report: a summary table and one diff block per changed file, without the pipeline's own files (rebuilt with the audit's fixes in the `commit` mode; not written without git)
- `<goal>-chain.json` next to the spec — the chain journal: stages `execution`, `diffs`, `commit`, unit progress, open questions of a stopped run, findings, commits
- `<goal>-followups.json` next to the journal — every out-of-scope defect of the goal, in the findings format `plan-brainstorming` accepts (`/plan-brainstorming <goal>-followups.json`)

`exec_dir` defaults to `<repo parent>/.exec/<repo>-<plan>/`: outside the project repository and stable across sessions. A directory inside the repository (unless git-ignored) or inside the OS temp dir is refused.

## Prerequisites

- Git for snapshots and rollback (without git, rollback is manual)
- Plan validated (ideally by `plan-iterative-revision`)
- Python ≥ 3.8

## Checklist Before Invoking

- [ ] Plan or roadmap exists and is finalized
- [ ] Repository is clean (or you accept that current changes go into the baseline)
- [ ] Environment ready for the first task
- [ ] If staged: roadmap points to existing `<base>-a.md`, `<base>-b.md`, … files

## Common Errors

| Symptom | Cause | Fix |
|---|---|---|
| `no-units` | No `### Task N:` headings | Re-run plan-writing, add headings, or use `--whole` |
| `duplicate-unit-id` | Two headings with the same id | Renumber the plan |
| `unknown-dependency` | Roadmap depends on a missing stage | Fix the roadmap table |
| `dirty-worktree` | Uncommitted changes at start (the pipeline's own files and `BACKLOG.md` do not count) | Commit/stash, or allow them into the baseline |
| `plan-drift` | Plan edited between sessions | New `exec_dir`, or accept the change |
| `settings-drift` | Spec (or plan header) settings edited between sessions | New `exec_dir`, or accept the changed settings |
| `settings-unavailable` | The spec named by `**Spec:**` is missing and the plan has External tasks | Restore the spec or fix the `**Spec:**` path |
| `exec-dir-inside-workdir` | Ledger directory inside the repo | Move `exec_dir` outside or git-ignore it |
| `exec-dir-ephemeral` | Ledger directory inside the OS temp dir | Use the default (`auto`), or `--allow-temp` for a throwaway run |
| `exhausted` / `stagnated` | Unit failed 3 times / same error twice | Read the stop-report, fix manually, resume |
| `commit`: `index-not-empty` | Changes already staged in the index | Commit or unstage them yourself, then `commit` again |
| `commit`: `mixed-files` | Files had your uncommitted work before the run, and the run changed them | Commit them by hand, or separate the changes |
| `commit`: `foreign-changes` | Files changed after the run's last task and not by the audit | Accept them when asked, or stop |
| `commit`: `baseline-head-unknown` | The ledger is older than the commit stage | Commit by hand; `<plan base>-diffs.md` lists the files |
| `commit`: `run-incomplete` | A task is still `running` (the run was interrupted) | Resume the run with `/plan-executor <plan>`, then `commit` again |
| `commit`: `failed-attempt` | A task failed and the files the commit would take differ from the last finished task (its half-done edits were not rolled back, or the files were changed outside the run) | The agent restores only these files to the last finished task (`checkpoint-restore --paths`, so the audit's fixes stay), then `commit` again; or commit by hand |
| `commit`: `head-moved` | You switched to a branch that does not contain the commit the run started from | Switch back, or commit by hand |
| `commit`: `ledger-ambiguous` | Both the plan and its roadmap have a run | The agent asks which run to commit (the two paths from the error) and commits the chosen one; without a confirmation channel the question stays open in the journal: answer it (`journal-answer`) and call `/plan-executor <plan> commit` again, it takes the answered path |

## Pipeline Position

```
plan-brainstorming → plan-writing → plan-iterative-revision → [plan-splitter] → [YOU ARE HERE] → plan-resolver → [YOU ARE HERE: commit]
```

**Previous:** `plan-writing` (plan) or `plan-splitter` (staged roadmap)
**Next:** `plan-resolver` (audit, or `auto` to audit and fix), then `/plan-executor <plan> commit`
