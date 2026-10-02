# TOOLING

All commands: `python "<SKILL_DIR>/scripts/executor_tool.py" <command> ...`. Output is one JSON object on stdout (UTF-8).

## Exit Codes

- `0` — success.
- `1` — contract violation: invalid ledger transition, `plan-drift`, `settings-drift`, `settings-unavailable`, `dirty-worktree`, a refused `consent` (`consent-prod-write`, `consent-denied`, `consent-unknown-environment`), git failure.
- `2` — input or filesystem problem: missing file or ledger, `no-units`, `duplicate-unit-id`, `unknown-dependency`, dependency cycle, `exec-dir-inside-workdir`, `checkpoint-restore --paths` with `unknown-path` (neither in the snapshot nor in the working tree; nothing is restored) or `invalid-path` (absolute or `..`).

Errors print `{"ok": false, "errors": ["..."]}`; `plan-drift` also carries `added` and `removed` unit ids, `settings-drift` carries `changed_keys` and `settings_source`, `settings-unavailable` carries `settings_errors`.

## Loop Commands

| Command | Purpose |
|---|---|
| `ledger-init <exec_dir\|auto> <plan> [--workdir R] [--whole] [--allow-dirty] [--accept-drift] [--allow-temp]` | Create or resume the ledger; baseline snapshot of `R`; the result carries the absolute `exec_dir` |
| `unit-begin <exec_dir>` | Next unit + `strategy` + its `text`, `files`, `external` entries (`env`, `access`, `kind`, `consent`, `confirmed`, `source`; recorded on the unit) and `foreign_changes` (`null` + `foreign_warning` when the check is off); marks it `running`. Files changed outside the run since the last unit → `reason: foreign-changes` with `foreign_changes`, `expected_tree`, `current_tree`, nothing marked |
| `consent <exec_dir> <env> read\|write` | Run-scope consent the engineer gave; refused for prod `write`, for `deny` and for an environment not in the settings |
| `accept-changes <exec_dir> [--note N]` | Keep the foreign changes: `expected_tree` = current tree, event in `foreign_events` |
| `unit-finish <exec_dir> <unit> pass\|fail [--error S] [--note N]…` | Snapshot + done, or failed + `decision`/`restore_to`. `--note` is repeatable: one note per agreed deviation and per External entry confirmed for this task only; each lands as its own `units[].notes` element |
| `run-diff <exec_dir>` | Files and `--stat` of what the run changed: baseline snapshot vs last unit snapshot |
| `checkpoint-restore <repo> <sha> [--paths F …] [--exec-dir D]` | Restore the working tree, or only the files `F`, to a snapshot or tree (confirmation required); `--exec-dir` moves `expected_tree` to the restored tree and records `--paths` restores. The executor always passes `--exec-dir` |
| `checkpoint-prune <exec_dir> [--workdir R]` | Delete this run's `refs/plan-executor/<run>/*` |

## Low-Level Commands

`detect-input`, `detect-lang <plan>`, `parse-roadmap`, `parse-tasks`, `ledger-next`, `ledger-mark`, `ledger-status`, `checkpoint-detect`, `checkpoint-create <repo> <label> [--run-id]`, `recommend-strategy`, `recommend-gate`, `scope-context`, `render-progress`. They exist for debugging and manual recovery; the loop above covers normal execution.

## Ledger

Schema: `assets/ledger.schema.json` (version 2: `source_sha256`, `run_id`, `workdir`, `baseline_checkpoint`, `expected_tree`, `foreign_events`, `settings`, `settings_source`, `consents`, per-unit `source`, `notes` and `external`). Version 1 ledgers are migrated on load; a ledger without `expected_tree` starts the check after its next `unit-finish`. `ledger-init` also prints `warnings` (not stored).
