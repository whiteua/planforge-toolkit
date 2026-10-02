# GATE

## Tiered Verification

- 🟢 green: run the relevant tests, lint, typecheck, or the narrowest executable check.
- 🟡 yellow: green checks plus a focused review of behaviour against the unit's done-state (Postconditions or `Done when:`).
- 🔴 red: yellow checks plus an adversarial subagent review where writer and grader are separate.

A checkpoint task (`### Task N: Checkpoint — …`) is gated by running its command and comparing the output with its `Expected:` line.

## External Units

`unit-begin` returns `external`: one entry per environment named before the description dash of each `**External:**` line (`` `a` (read), `b` (write) — … `` gives two entries), `{env, access, kind, consent, confirmed, source}`, also recorded on the unit in the ledger. `consent` is the setting for that access (`run`, `task`, `deny`) from the settings `ledger-init` stored (the spec, or the header of an old plan); settings stored with errors grant nothing (`consent: null`). `confirmed` is true for `run` or for a run-scope consent given earlier with `consent`, never for a write on production; `source` says whose permission it is (`spec` / `session`).

- **Confirmed** — no question. Say it in one line in the plan's language (environment, read or write, `source`) and run the unit. A prod read with `read=run` runs the same way; the ledger entry and the resolver hand-off (RESOLVER-PROPOSAL.md) keep it.
- **`consent: deny`** — STOP: the plan asks for access the settings forbid, so the plan must change. Do not ask for an exception.
- **Environment not in the settings** — an entry with `kind: null` while `settings.from` is `spec` or `plan-header` — STOP: the plan does not list it. Take `settings.from` from the `ledger-init` result (`settings.from`) or from `<exec_dir>/state.json` (`settings.from`; `settings: null` when `plan-brainstorming` is not installed). With `settings.from: none` (a plan without `**Spec:**`) or settings `null`, `kind: null` says nothing: ask as below.
- **Otherwise** (`task`, an old line without `(read)`/`(write)`, `settings.from: none`, settings `null`) — ask before running the unit. Name the changes first and explicitly (what will be changed, on which environment), then the reads, then the commands. Options, in the plan's language:
  - for an entry with `access` (`read` or `write`) whose environment is in the settings (`kind` not null): **only this task** / **the whole run** / **stop**. "The whole run" → `consent <exec_dir> <env> <access>`; the tool refuses `write` on prod (`consent-prod-write`: changes on prod are confirmed task by task), any `deny` (`consent-denied`) and an environment missing from the settings (`consent-unknown-environment`): then offer "only this task" or stop;
  - for an old line without `(read)`/`(write)` (`access: null`), for `settings.from: none` and for settings `null`: only **only this task** / **stop**. A run-scope consent cannot be recorded there, so the question comes again before every such unit.
- **"Only this task"** is recorded in the ledger, so the resolver hand-off can show who allowed the access: finish that unit with `unit-finish <exec_dir> <unit> pass --note "External: <env> (<access>) confirmed by the engineer for this task"`; pass `--note` once per confirmed entry (`--note` is repeatable, and an agreed deviation of the same unit is one more `--note`). `<access>` is `read`, `write` or `unspecified` for an old line. Each note lands as its own element of `units[].notes`.
- **No confirmation channel** (autonomous run, subagent) and an unconfirmed entry — STOP with a stop-report: environment, read or write, the command.

Run the step only on the environment it names; if a project script targets another environment, do not run it: stop and ask.

## Deviations

When the gate (or its reviewer) finds a defect outside the unit's text, do not fix it silently. Ask the engineer; with consent, fix it within the unit and record it: `unit-finish <unit> pass --note "<what was done beyond the plan and why>"`. Without consent, leave it and list it in the FINALIZE follow-ups.

## No Tests → Escalate

If no executable check exists, do not claim success by inspection alone: use grader or human review and record the evidence.

## Foreign Changes

`unit-begin` returns `reason: foreign-changes` when the working tree differs from the ledger's `expected_tree` (the last snapshot, or the tree at the last failed attempt): files were changed outside the run between units. `foreign_changes` lists `{path, status}` (`added`/`modified`/`deleted`); `BACKLOG.md` at the repository root is never listed. No unit is marked running.

Show the engineer the list and ask one question with three options:

1. **Accept** — the changes stay and become part of the run: `accept-changes <exec_dir> --note "<why, in the engineer's words>"`.
2. **Restore these files** — `checkpoint-restore <repo> <expected_tree> --paths <file> … --exec-dir <exec_dir>`, with the `expected_tree` from the `unit-begin` result and the files the engineer named. Modified and deleted files come back, added files are deleted; listed files the engineer did not name stay and are recorded as accepted. `unknown-path` (exit `2`) restores nothing: check the names against the list.
3. **Stop** — STOP with a stop-report that lists the files.

Then call `unit-begin` again. Without a confirmation channel (autonomous run), do not choose: STOP with a stop-report listing every path with its status.

## Retry & Rollback

On gate failure call `unit-finish <unit> fail --error "<signature>"`. It returns:

- `decision: retry` — ask the engineer to confirm `checkpoint-restore <repo> <restore_to> --exec-dir <exec_dir>` (or to keep the current state), then call `unit-begin` again; it returns the same unit as `retry-available`. The executor's own restores always pass `--exec-dir`: it moves `expected_tree` to the restored tree, otherwise the retry is reported as `foreign-changes`.
- `decision: stop` — `stop_reason` is `exhausted` (3 attempts) or `stagnated` (same signature twice). STOP with a stop-report.

## Restore Requires Confirmation

`checkpoint-restore` rewrites working-tree files to the snapshot and deletes files created after it (branch, HEAD and index stay unchanged); with `--paths` it does this only for the named files. `BACKLOG.md` at the repository root is never deleted or rewritten by a restore. It is destructive for uncommitted work: the agent MUST obtain explicit engineer confirmation first. In auto mode without a confirmation channel, STOP with a stop-report instead of restoring.
