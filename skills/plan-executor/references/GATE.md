# GATE

## Tiered Verification

- 🟢 green: run the relevant tests, lint, typecheck, or the narrowest executable check.
- 🟡 yellow: green checks plus an LLM grader or focused review of behavior against the unit contract.
- 🔴 red: yellow checks plus adversarial subagent review where writer and grader are separate.

## Retry & Rollback

On gate failure, restore the previous checkpoint with `checkpoint-restore` when git is available. In step mode, ask the engineer for manual rollback or confirmation. Retry the same unit until `attempts >= 3`; then STOP and generate a stop-report.

## No Tests → Escalate

If no executable check exists, do not claim success by inspection alone. Нет тестов — эскалация, **не фейк-пас**: use grader/human review and record the evidence.

## Checkpoint Failure = Gate Failure

If `checkpoint-create` fails, do not call `ledger-mark done`. Treat the checkpoint failure as gate failure, preserve `last_error`, and retry or STOP according to the attempts policy.

## Restore Requires Confirmation

`checkpoint-restore` executes `git reset --hard` - a destructive, irreversible operation. The agent MUST obtain explicit engineer confirmation before calling it. In auto-mode, if no confirmation channel is available, the agent must STOP and generate a stop-report instead of restoring silently.
