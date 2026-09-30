# TOOLING

All commands: `python "<SKILL_DIR>/scripts/executor_tool.py" <command> ...`. Output is one JSON object on stdout (UTF-8).

## Exit Codes

- `0` — success.
- `1` — contract violation: invalid ledger transition, `plan-drift`, `dirty-worktree`, git failure.
- `2` — input or filesystem problem: missing file or ledger, `no-units`, `duplicate-unit-id`, `unknown-dependency`, dependency cycle, `exec-dir-inside-workdir`.

Errors print `{"ok": false, "errors": ["..."]}`; `plan-drift` also carries `added` and `removed` unit ids.

## Loop Commands

| Command | Purpose |
|---|---|
| `ledger-init <exec_dir\|auto> <plan> [--workdir R] [--whole] [--allow-dirty] [--accept-drift] [--allow-temp]` | Create or resume the ledger; baseline snapshot of `R`; the result carries the absolute `exec_dir` |
| `unit-begin <exec_dir>` | Next unit + `strategy` + its `text`, `files` and `external` lines; marks it `running` |
| `unit-finish <exec_dir> <unit> pass\|fail [--error S] [--note N]` | Snapshot + done (with an agreed-deviation note), or failed + `decision`/`restore_to` |
| `run-diff <exec_dir>` | Files and `--stat` of what the run changed: baseline snapshot vs last unit snapshot |
| `checkpoint-restore <repo> <sha>` | Restore the working tree to a snapshot (confirmation required) |
| `checkpoint-prune <exec_dir> [--workdir R]` | Delete this run's `refs/plan-executor/<run>/*` |

## Low-Level Commands

`detect-input`, `detect-lang <plan>`, `parse-roadmap`, `parse-tasks`, `ledger-next`, `ledger-mark`, `ledger-status`, `checkpoint-detect`, `checkpoint-create <repo> <label> [--run-id]`, `recommend-strategy`, `recommend-gate`, `scope-context`, `render-progress`. They exist for debugging and manual recovery; the loop above covers normal execution.

## Ledger

Schema: `assets/ledger.schema.json` (version 2: `source_sha256`, `run_id`, `workdir`, `baseline_checkpoint`, per-unit `source` and `notes`). Version 1 ledgers are migrated on load.
