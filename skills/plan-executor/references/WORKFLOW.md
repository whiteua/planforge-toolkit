# WORKFLOW

## BOOTSTRAP

1. `ledger-init <exec_dir> <plan_path> --workdir <repo>` detects the input (roadmap or whole plan), parses units, writes `state.json`, and takes a baseline snapshot of `<repo>`; its tree becomes `expected_tree`, the state the working tree must have before the next unit.
2. `exec_dir` MUST be outside `<repo>` or git-ignored; otherwise `exec-dir-inside-workdir`. Snapshots and restores then never touch `state.json`. Pass `auto` to get the default `<repo parent>/.exec/<repo>-<plan>/`. A directory inside the OS temp dir is refused with `exec-dir-ephemeral` (the ledger would vanish with the session); `--allow-temp` overrides it for throwaway runs. The result's `exec_dir` field is the absolute path: report it to the engineer.
3. A dirty working tree gives `dirty-worktree`: ask the engineer to commit/stash, or re-run with `--allow-dirty` (the baseline then includes those changes). `BACKLOG.md` at the repository root does not count: the skills append to it between runs.
4. Without git (`workdir` not a repository) snapshots are `null`: rollback is manual, so ask the engineer before every retry.
5. Re-running `ledger-init` on an existing ledger resumes it: `running` units go back to `pending`. If the plan file changed, `plan-drift` returns the `added`/`removed` unit ids — STOP and ask. Continue only with a new `exec_dir` or `--accept-drift` (units are rebuilt; `done` units with the same id are kept). When a unit was still `running` (the session ended mid-unit), its files become the expected tree, so the next `unit-begin` does not report them as foreign changes.
6. `ledger-init` reads the chain settings by the shared rule (`resolve_settings` of `plan-brainstorming`: the plan header when it has settings, else the spec named by `**Spec:**`; a roadmap goes through its `Source` link to the master plan) and stores them as `settings` and `settings_source` (path and SHA-256). Show the result's `warnings`. Without `plan-brainstorming` alongside, `settings` is `null` and every External unit is asked. `settings-unavailable` (the spec cannot be read and the plan has External units): STOP and ask; without a confirmation channel, stop with a report. A resume clears the run-scope `consents` and compares the source's SHA-256: a change is `settings-drift` with `changed_keys` — STOP and ask; continue only with a new `exec_dir` or `--accept-drift` (the new settings are adopted). A source that can no longer be read on resume is not a drift: the stored settings stay and `settings-unavailable` applies as above.

## LOOP

`unit-begin` returns one of these reasons:

| `reason` | Meaning | Action |
|---|---|---|
| `ready` | Next pending unit, dependencies done; marked `running` | Execute, gate, `unit-finish` |
| `retry-available` | The failed unit, retryable; marked `running` | Same as `ready`; fix the recorded `last_error` first |
| `in-progress` | A unit is still `running` | Gate the current state, `unit-finish` |
| `foreign-changes` | Files changed outside the run since the last unit (`foreign_changes`); nothing marked `running`. Not checked for `in-progress`; `null` + `foreign_warning` outside git or for an old ledger | Ask: accept / restore these files / stop (GATE.md, Foreign Changes); silent run → STOP, stop-report with the files |
| `exhausted` | 3 attempts used | STOP, stop-report |
| `stagnated` | The same error signature twice in a row | STOP, stop-report |
| `blocked` | Pending units wait on `blocked_by` | STOP, stop-report |
| `all-done` | Every unit is done | FINALIZE |

A failed unit is always handled before any other unit, so later units never run on top of a broken one. In whole plans units are strictly sequential (each depends on the previous one).

`unit-finish <unit> pass` snapshots `<repo>` into `refs/plan-executor/<run>/<unit>`, marks the unit done with that snapshot and renders `progress.md`. If the snapshot fails the unit is marked failed instead (checkpoint failure = gate failure). `expected_tree` becomes the snapshot's tree.

`unit-finish <unit> fail --error "<signature>"` marks the unit failed and returns `decision` and `restore_to` (last done unit's snapshot, or the baseline). Use a short, stable signature — e.g. the failing test id plus the assertion — so stagnation detection can compare attempts (case and whitespace are ignored). `expected_tree` becomes the tree at the failure, so a retry without a restore is not reported as foreign; a restore passes `--exec-dir <exec_dir>`.

## Subagents

Subagents may inspect code and return diff/status/logs. Only the parent session calls `unit-finish`, marks units, or decides the gate.

## FINALIZE

1. Render final progress.
2. `run-diff <exec_dir>`: show `stat` and give the engineer `command` for the full diff. It compares the baseline snapshot with the last unit's snapshot, so work that was uncommitted before the run is not mixed in.
3. Findings outside the plan's scope (defects noticed on the way, not fixed, including the GATE.md follow-ups). Skip this step when there are none. Otherwise:
   - Append each one to the shared `BACKLOG.md`: `python "<SKILL_DIR>/../plan-brainstorming/scripts/brainstorm_tool.py" backlog-append <root> --section <S> --source "plan-executor, <plan file name>" --item "<path:line — summary>" --lang <plan language>`.
   - `<root>` = `git -C <plan dir> rev-parse --show-toplevel`; outside git, the current working directory.
   - `<S>` = `settings.backlog` from the ledger (`<exec_dir>/state.json`, read only); a ledger without `settings` → `backlog` of `brainstorm_tool.py settings <plan>`; still none → the master plan's file name without `.md` and `-impl` (`values-fix-1-impl.md` → `values-fix-1`; for a roadmap, the master plan of its Source line).
   - `action: exists` is fine. The script is missing (`plan-brainstorming` not installed alongside) or exits `1`: append the line by hand at the end of section `<S>` in the same format, `- [ ] <item> — plan-executor, <plan file name>, <YYYY-MM-DD>` (create `# Backlog`, the user section `## My notes` / `## Свои заметки` and `## <S>` when missing; change nothing else), and say so in the final summary.
   - Write the same items to `<plan base>-followups.json` next to the plan, as a JSON array of `{file, line, summary, failure_scenario}`: the machine input of `plan-brainstorming` (`/plan-brainstorming <plan base>-followups.json`).
4. Propose `plan-resolver` per `RESOLVER-PROPOSAL.md`.
5. Offer `checkpoint-prune <exec_dir>` to delete the run's snapshot refs.
