# GATE

## Tiered Verification

- 🟢 green: run the relevant tests, lint, typecheck, or the narrowest executable check.
- 🟡 yellow: green checks plus a focused review of behaviour against the unit's done-state (Postconditions or `Done when:`).
- 🔴 red: yellow checks plus an adversarial subagent review where writer and grader are separate.

A checkpoint task (`### Task N: Checkpoint — …`) is gated by running its command and comparing the output with its `Expected:` line.

## No Tests → Escalate

If no executable check exists, do not claim success by inspection alone: use grader or human review and record the evidence.

## Retry & Rollback

On gate failure call `unit-finish <unit> fail --error "<signature>"`. It returns:

- `decision: retry` — ask the engineer to confirm `checkpoint-restore <repo> <restore_to>` (or to keep the current state), then call `unit-begin` again; it returns the same unit as `retry-available`.
- `decision: stop` — `stop_reason` is `exhausted` (3 attempts) or `stagnated` (same signature twice). STOP with a stop-report.

## Restore Requires Confirmation

`checkpoint-restore` rewrites working-tree files to the snapshot and deletes files created after it (branch, HEAD and index stay unchanged). It is destructive for uncommitted work: the agent MUST obtain explicit engineer confirmation first. In auto mode without a confirmation channel, STOP with a stop-report instead of restoring.
