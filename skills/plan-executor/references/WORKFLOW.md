# WORKFLOW

## BOOTSTRAP

1. `ledger-init <exec_dir> <plan_path> --workdir <repo>` detects the input (roadmap or whole plan), parses units, writes `state.json`, and takes a baseline snapshot of `<repo>`.
2. `exec_dir` MUST be outside `<repo>` (e.g. sibling to the repository) or git-ignored; otherwise `exec-dir-inside-workdir`. Snapshots and restores then never touch `state.json`.
3. A dirty working tree gives `dirty-worktree`: ask the engineer to commit/stash, or re-run with `--allow-dirty` (the baseline then includes those changes).
4. Without git (`workdir` not a repository) snapshots are `null`: rollback is manual, so ask the engineer before every retry.
5. Re-running `ledger-init` on an existing ledger resumes it: `running` units go back to `pending`. If the plan file changed, `plan-drift` returns the `added`/`removed` unit ids — STOP and ask. Continue only with a new `exec_dir` or `--accept-drift` (units are rebuilt; `done` units with the same id are kept).

## LOOP

`unit-begin` returns one of these reasons:

| `reason` | Meaning | Action |
|---|---|---|
| `ready` | Next pending unit, dependencies done; marked `running` | Execute, gate, `unit-finish` |
| `retry-available` | The failed unit, retryable; marked `running` | Same as `ready`; fix the recorded `last_error` first |
| `in-progress` | A unit is still `running` | Gate the current state, `unit-finish` |
| `exhausted` | 3 attempts used | STOP, stop-report |
| `stagnated` | The same error signature twice in a row | STOP, stop-report |
| `blocked` | Pending units wait on `blocked_by` | STOP, stop-report |
| `all-done` | Every unit is done | FINALIZE |

A failed unit is always handled before any other unit, so later units never run on top of a broken one. In whole plans units are strictly sequential (each depends on the previous one).

`unit-finish <unit> pass` snapshots `<repo>` into `refs/plan-executor/<run>/<unit>`, marks the unit done with that snapshot and renders `progress.md`. If the snapshot fails the unit is marked failed instead (checkpoint failure = gate failure).

`unit-finish <unit> fail --error "<signature>"` marks the unit failed and returns `decision` and `restore_to` (last done unit's snapshot, or the baseline). Use a short, stable signature — e.g. the failing test id plus the assertion — so stagnation detection can compare attempts (case and whitespace are ignored).

## Subagents

Subagents may inspect code and return diff/status/logs. Only the parent session calls `unit-finish`, marks units, or decides the gate.

## FINALIZE

Render final progress, propose `plan-resolver` per `RESOLVER-PROPOSAL.md`, and offer `checkpoint-prune <exec_dir>` to delete the run's snapshot refs.
