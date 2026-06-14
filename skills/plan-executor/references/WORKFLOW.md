# WORKFLOW

## BOOTSTRAP

1. Run `detect-input <plan_path>`.
2. For staged input, run `parse-roadmap <roadmap_path>` and `recommend-parallel <exec_dir>` after ledger init.
3. For whole input, run `parse-tasks <plan_path>`; if no units are found, stop and follow `INPUT-DETECTION.md`.
4. Run `ledger-init <exec_dir> <plan_path>`; the ledger is the only source of truth.
5. Run `checkpoint-detect <workdir>` before auto execution. Without git, auto rollback is unavailable; use step mode.
6. The `exec_dir` MUST be located outside the workdir (e.g., sibling to plan files). This guarantees `git add -A` and `git reset --hard` in workdir never touch `state.json`. Never place `.exec/` inside the repository being modified.

## EXECUTE LOOP

1. Run `ledger-next <exec_dir>` to choose the next executable unit.
2. Run `recommend-strategy <weight> --task-text <text>` for `{isolation, model_depth, gate_tier}`.
3. Run `scope-context <stage_path>` and let the agent read returned paths itself.
4. Run `ledger-mark <exec_dir> <unit> running` to claim the unit and start the attempt counter.
5. Execute exactly one unit.
6. Gate the result according to `GATE.md`.
7. On success: `checkpoint-create`, then `ledger-mark <unit> done --checkpoint <sha>`, then `render-progress`.
8. On failure: `ledger-mark <unit> failed --error "<message>"`, then retry or STOP.

## Reason Dispatch

| `ledger-next` reason | Action |
|---|---|
| `ready` | Proceed with execute loop (steps 2-8). |
| `retry-available` | Same as `ready` - the unit is failed and eligible for another attempt. |
| `all-done` | Exit loop, proceed to FINALIZE. |
| `blocked` | All pending units depend on incomplete predecessors. Retry the failed predecessor first (it will be returned as `retry-available` in a subsequent `ledger-next` call). Once the predecessor completes, the blocked unit becomes `ready`. If no predecessor is retryable - STOP. |
| `no-pending` | No pending and no retryable failed units remain. STOP with stop-report. |

## FINALIZE

When `ledger-next` returns `all-done`, render final progress and propose `plan-resolver` according to `RESOLVER-PROPOSAL.md`.

## Subagent Isolation Protocol

Subagents may inspect code and return diff/status/logs, but `ledger-mark только родитель`. A subagent never edits `state.json`, never marks a unit done, and never decides final gate status alone.

## Retry & Attempts

`attempts` increments when a unit is marked running. `attempts >= 3` means STOP: one primary attempt plus two retries are exhausted.

## Stagnation Detection

If the new failure has identical `last_error` to the previous failure, `identical last_error → STOP`. Do not spend attempts on the same unresolved failure signature.

## Checkpoint Atomicity

`checkpoint-create` must succeed before `ledger-mark done`. If checkpoint creation fails, treat it as gate failure and keep the unit not-done.
