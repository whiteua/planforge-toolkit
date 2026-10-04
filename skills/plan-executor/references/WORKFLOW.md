# WORKFLOW

## Chain journal

`J` = `python "<SKILL_DIR>/../plan-brainstorming/scripts/brainstorm_tool.py"`. `J journal-path <plan or roadmap> --create`
gives `journal` (`<journal>` below) and `plan`: `P`, the master plan (a roadmap or a part leads to
it). Every `--plan` below is `P`.

Before a stage of this skill runs (`execution` before `ledger-init`, `diffs` in FINALIZE, `commit`
in COMMIT), read it from `J journal-show <journal> --plan <P>` (`unknown-plan`, exit `2`: no event
of this plan yet, every stage is `pending`):

| Stage status | Before the stage runs |
|---|---|
| `pending`, `running` | nothing to ask; `ledger-init` moves `execution` itself, the agent moves `diffs` and `commit` (FINALIZE, COMMIT) |
| `failed` | the open questions of this stage first (as for `stopped` below); then `ledger-init` retries `execution`, the agent retries `diffs` and `commit` |
| `stopped` with `open_questions` | with a confirmation channel: ask each question (its `text` and `options`) in the plan's language and record `J journal-answer <journal> <Qn> --answer "<answer>"`; without one: STOP and name the open ids, nothing else runs |
| `stopped`, every question answered | apply each answer (it decides how the stage continues: retry, restore, accept, commit by hand, …), then `J journal-answer <journal> <Qn> --applied`; the stage continues with its normal resume. For `execution`: `ledger-init` first (a resume clears the run-scope consents), then the answer (an External confirmation: `consent <exec_dir> <env> <access>`), then `--applied`, then `unit-begin` |
| `done` | `execution`: the drift check first. `J journal-reconcile <journal>`, then look in the journal file's `questions` for one of `P` whose text starts with `drift: execution` and that is not `applied` (the plan or roadmap changed after the run). `open` → as for `stopped` with open questions (record the answer `rewrite` or `keep`); answered `rewrite` → `J journal-event <journal> --skill plan-executor --plan <P> --stage execution --status running --reason drift` before `ledger-init` (its `plan-drift` then needs a new `exec_dir` or `--accept-drift`, BOOTSTRAP 5), and `J journal-answer <journal> <Qn> --applied` once the stage is `done` again; answered `keep` → `J journal-answer <journal> <Qn> --applied`, then `J journal-event <journal> --skill plan-executor --plan <P> --stage execution --status done --input <plan or roadmap>` (the same status: it binds the stage to the current input without a new run). No such question, or another stage: say that the stage is done and name the next one (`owner` of `current` in `journal-show`); only `commit` runs again, with `--reason recommit` (COMMIT) |

`journal-show` gives a plan `next_action: answer` while any question of it is open, on a stage in
any status (`owner` = the stage of the first open question): an open question of this skill's
stage is handled as in the `stopped` row whatever the stage's status (`done` and `failed`
included) before anything else runs.

A question recorded without `--answer` stops the stage only when the stage is `running`: it
becomes `stopped`; after `exhausted`/`stagnated`/`blocked` it stays `failed` with the question
open. So a STOP without a confirmation channel in BOOTSTRAP (`dirty-worktree`, `plan-drift`,
`settings-drift`, `settings-unavailable`), which comes before `ledger-init` moved the stage, first
records `J journal-event <journal> --skill plan-executor --plan <P> --stage execution --status running`
(from `pending`, `failed` or a `stopped` stage whose questions are all applied), then the
`journal-question`, then `J journal-export-findings <journal>` and the stop report. `ledger-init`
cannot move a `stopped` stage that has open questions (its result then carries `journal_error`)
and would retry a `failed` one past its question, so the questions are handled first.

Journal errors never block the run's own work:
- exit `2` `journal-corrupt` → say it in one line, propose `J journal-reconcile <journal> --rebuild`,
  continue without the journal;
- exit `1` `journal-locked` → repeat the command once; still locked: with a confirmation channel
  ask whether to continue without the journal, without one STOP with a stop report;
- exit `1` `journal-write-failed` (the file system refused the write, e.g. a read-only journal) →
  say it in one line with the error text and continue without the journal;
- exit `1` `illegal-transition` or `open-questions` → never force another status: show
  `J journal-show <journal> --plan <P>` and act by the table above.

## BOOTSTRAP

1. `ledger-init <exec_dir> <plan_path> --workdir <repo>` detects the input (roadmap or whole plan), parses units, writes `state.json`, and takes a baseline snapshot of `<repo>`; its tree becomes `expected_tree`, the state the working tree must have before the next unit. For a roadmap the units are the tasks of its parts plus one checkpoint `part-<id>-done` per part (INPUT-DETECTION.md).
2. `exec_dir` MUST be outside `<repo>` or git-ignored; otherwise `exec-dir-inside-workdir`. Snapshots and restores then never touch `state.json`. Pass `auto` to get the default `<repo parent>/.exec/<repo>-<plan>/`. A directory inside the OS temp dir is refused with `exec-dir-ephemeral` (the ledger would vanish with the session); `--allow-temp` overrides it for throwaway runs. The result's `exec_dir` field is the absolute path: report it to the engineer.
3. A dirty working tree gives `dirty-worktree`: ask the engineer to commit/stash, or re-run with `--allow-dirty` (the baseline then includes those changes). `BACKLOG.md` at the repository root does not count: the skills append to it between runs. Neither do the pipeline's own files (GATE.md, Foreign Changes: specs, plans, parts, roadmaps, completion, review and report files, `*-diffs.md`, `*-followups.json`) and the run's chain journal; a `*-chain.json` other than the run's journal does.
4. Without git (`workdir` not a repository) snapshots are `null`: rollback is manual, so ask the engineer before every retry.
5. Re-running `ledger-init` on an existing ledger resumes it: `running` units go back to `pending`. If the plan file changed, `plan-drift` returns the `added`/`removed` unit ids — STOP and ask. Continue only with a new `exec_dir` or `--accept-drift` (units are rebuilt; `done` units with the same id are kept). When a unit was still `running` (the session ended mid-unit), its files become the expected tree, so the next `unit-begin` does not report them as foreign changes.
6. `ledger-init` reads the chain settings by the shared rule (`resolve_settings` of `plan-brainstorming`: the plan header when it has settings, else the spec named by `**Spec:**`; a roadmap goes through its `Source` link to the master plan) and stores them as `settings` and `settings_source` (path and SHA-256). Show the result's `warnings`. Without `plan-brainstorming` alongside, `settings` is `null` and every External unit is asked. `settings-unavailable` (the spec cannot be read and the plan has External units): STOP and ask; without a confirmation channel, stop with a report. A resume clears the run-scope `consents` and compares the source's SHA-256: a change is `settings-drift` with `changed_keys` — STOP and ask; continue only with a new `exec_dir` or `--accept-drift` (the new settings are adopted). A source that can no longer be read on resume is not a drift: the stored settings stay and `settings-unavailable` applies as above.
7. `ledger-init` also stores the chain journal (`journal`: its path and the master plan's id) and `baseline_head` (the `HEAD` of the first `ledger-init`, `""` for a repository without commits; the COMMIT stage needs it), and moves the journal's `execution` stage to `running` with the artifact `exec_dir` (relative to the journal's directory, forward slashes; absolute only on another drive). `unit-begin` and `unit-finish` write the unit events with `done`/`total`, `unit-finish` keeps the stage's artifacts `units_done` and `units_total` current, and `unit-begin` ends the stage: `done` at `all-done`, `failed` at `exhausted`, `stagnated` or `blocked`. A `journal_error` in a result: say it in one line and continue.

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

`unit-begin` returned `all-done` and moved the `execution` stage to `done`.

1. Render final progress.
2. Diff report. `<diffs>` = `<dir of P>/<file name of P without -impl.md, else without .md>-diffs.md` (for a roadmap `P` is the source plan, so a split plan has one report). Stage `diffs` `pending`, `failed` or `stopped` (no open questions) → first `J journal-event <journal> --skill plan-executor --plan <P> --stage diffs --status running`. Then `run-diff <exec_dir> --markdown <diffs>`; it compares the baseline snapshot with the last unit's snapshot, so work that was uncommitted before the run is not mixed in, and leaves out the pipeline artifacts (`excluded`):
   - exit `0` → `J journal-event <journal> --skill plan-executor --plan <P> --stage diffs --status done --artifact diffs=<diffs relative to the journal's directory, forward slashes>`; give the engineer the report path and the number of `files`. A report rebuilt over a `done` stage uses the same command (same status: the artifacts are updated and the journal records `diffs-rebuilt`). `pending` never goes straight to `done`: `running` comes first;
   - exit `1` `no-git` → `--status skipped --data '{"why": "no-git"}'`; say that there is no diff report because the project is not a git repository;
   - exit `1` `run-diff-unavailable` → `--status skipped --data '{"why": "run-diff-unavailable"}'`; say that no unit has a snapshot.
   Without a journal, run the same `run-diff` and only report the result.
3. Findings outside the plan's scope (defects noticed on the way and not fixed, GATE.md, Deviations) are recorded when they are noticed; record now any that are still only in your notes, one command each:
   `J journal-finding <journal> --skill plan-executor --plan <P> --file <path from the repository root> [--line N] --summary "<what is wrong>" --failure-scenario "<what breaks, and when>" --backlog-root <root>`
   - `<root>` = `git -C <dir of P> rev-parse --show-toplevel`; outside git, the current working directory. The finding is appended to the goal's section of the shared `BACKLOG.md` at once; `action: exists` (same file and summary) is fine.
   - `backlog: failed` (with `backlog_error`): the finding is still recorded in the journal and goes into `<goal>-followups.json`; only its `BACKLOG.md` line is missing. Append that line by hand at the end of section `<S>`, `- [ ] <summary> (<path>:<line>) — plan-executor, <plan file name>, <YYYY-MM-DD>` (the item format of `journal-finding`) (create `# Backlog`, the user section `## My notes` / `## Свои заметки` and `## <S>` when missing; change nothing else), and say so in the final summary. Exception: `backlog_error` starting with `user-section:` means `<S>` is the user's own section (`My notes` / `Свои заметки`, any case): it is never written, not even by hand; say so in the final summary instead.
   - No journal: with `plan-brainstorming` alongside (the journal is `journal-corrupt`), `python "<SKILL_DIR>/../plan-brainstorming/scripts/brainstorm_tool.py" backlog-append <root> --section <S> --source "plan-executor, <plan file name>" --item "<path:line — summary>" --lang <plan language>`; `action: exists` is fine, exit `1` with `user-section:` writes nothing at all, any other exit `1` → by hand as above. Without `plan-brainstorming`, by hand as above. Say so in the final summary.
   - `<S>` = the journal's `goal`; without a journal, `settings.backlog` from the ledger (`<exec_dir>/state.json`, read only), else the master plan's file name without `.md` and `-impl` (`values-fix-1-impl.md` → `values-fix-1`).
   Then `J journal-export-findings <journal>` (with no findings and no file the file is `[]`; items already in the file stay, the journal's findings it lacks are added; a file that is unreadable or not a JSON list gives `followups-unreadable`, exit `2`, and is left unchanged: name it in the stop report). Its `path` is `<goal>-followups.json` next to the journal, the machine input of the next cycle (`/plan-brainstorming <goal>-followups.json`); name it in the summary.
4. Propose `plan-resolver` per `RESOLVER-PROPOSAL.md`. Unfinished units are named by their ids: `task-<N>` is Task N of the master plan (also in a roadmap run), `part-<id>-done` the checkpoint of part `<id>`.
5. Do not offer `checkpoint-prune` here: the COMMIT stage diffs and commits from the run's snapshots. It is offered when COMMIT is `done`.

## COMMIT

`/plan-executor <plan> commit`: a separate call after the audit (the resolver's gate names it) or after `resolver=skip`. It commits only the run's files and the audit's fixes, with the repository's hooks. Never `--no-verify`, `--amend`, `push` or `--force`; nothing else in this mode changes git, and the engineer's index is never unstaged by the agent.

1. **Find.** `ledger-path <plan> --workdir <repo>` → `exec_dir`, `exists`, `matched` (read only: the consents and the settings check stay as they are). A split plan is usually run from its roadmap: for `<X>.md` with a `<X>-roadmap.md` beside it the command looks at the ledgers of both (and for a roadmap, at its master plan's too), returns the one that exists and names it in `matched` (`plan` or `roadmap`). Exit `2` `ledger-ambiguous` (both ledgers exist; the two paths are in the error's `exec_dirs`) → do not call `ledger-path` again; first `J journal-path <plan> --create` → `<journal>`, `P` (the master plan, also when `<plan>` was the roadmap; `<diffs>` is built from `P`), then `<exec_dir>` is the path chosen from `exec_dirs`. With a confirmation channel ask which run to commit (the two paths as options) and record the answer with `J journal-question <journal> --skill plan-executor --plan <P> --stage commit --text "ledger-ambiguous: which run to commit?" --option "<path 1>" --option "<path 2>" --answer "<chosen path>"`. Without one: start the stage as in step 2 (so the question stops it), `J journal-question <journal> --skill plan-executor --plan <P> --stage commit --text "ledger-ambiguous: which run to commit?" --option "<path 1>" --option "<path 2>"`, `J journal-export-findings <journal>`, and stop with a short report naming the question id; the next `commit` call takes the answered question's answer as `<exec_dir>` (after `J journal-answer <journal> <Qn> --applied`). `exists: false` → STOP: there is no run of this plan to commit; name `/plan-executor <plan>`. Then `J journal-path <plan> --create` → `<journal>`, `P` (already done in the `ledger-ambiguous` branch), and `J journal-show <journal> --plan <P>` for stage `commit` (Chain journal).
2. **Start.** `J journal-event <journal> --skill plan-executor --plan <P> --stage commit --status running --artifact declined=no --artifact empty=no`; add `--reason recommit` when the stage is `done` (a later call after new audit fixes). The two artifacts reset the outcome of an earlier call: `declined=yes` and `empty=yes` are set only by their own outcomes below.
3. **Diff report with the fixes.** `run-diff <exec_dir> --markdown <diffs> --include-fixes <journal>` (`<diffs>` as in FINALIZE), then record it like FINALIZE step 2 (`diffs` not `done` yet: `--status running` first, then `done`; already `done`: the same-status `J journal-event <journal> --skill plan-executor --plan <P> --stage diffs --status done --artifact diffs=<diffs relative to the journal's directory>` updates it, recorded as `diffs-rebuilt`). The result's `fix_files` are the files the audit changed (marked "fixed by the audit" in the report); its `excluded` are run files left out as pipeline artifacts, listed in the report's section "Not included (pipeline artifacts)" («Не включены (артефакты конвейера)»); its `ignored` are audit fix files git ignores (no snapshot or tree holds them, and `commit-run` does not commit them), listed in the section "Not included (ignored by git)" («Не включены (игнорируются git)»): name them to the engineer. `no-git` → `diffs` and `commit` both `--status skipped --data '{"why": "no-git"}'`: say that nothing is committed without git, and stop. `run-diff-unavailable` → `commit` `--status skipped --data '{"why": "run-diff-unavailable"}'`: no unit finished, nothing to commit. A journal error of `--include-fixes` (exit `2`: `journal-missing`, `journal-corrupt`, `journal-plan-unknown`, `journal-unavailable`, `invalid-path` for a bad `fix_files` entry) or no journal at all → say it and rebuild the report without `--include-fixes`; the files the audit fixed are then unknown: those the run also changed come back from `commit-run` as `foreign-changes` (step 6), while files only the audit changed are not in the commit set at all and stay uncommitted: name them to the engineer (the resolver's report lists them) to commit by hand.
4. **Message file**, written to the OS temp directory (never inside the repository):
   - subject `<type>(<scope>): <subject>` of at most 72 characters: `<type>` is one of `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, `perf`, `style`, chosen by what the plan does; `<scope>` = the plan file name of `P` without `-impl.md`. When the journal already has a commit of this run (`stages.commit.artifacts.commits` not empty), this call commits only new audit fixes: `fix(<scope>): …`. Stage artifacts are read from the journal file itself (the `plans` entry with `id` `P`), not from `journal-show`, which returns statuses only;
   - body: the spec's `# Goal` paragraph (the plan's `**Goal:**` when there is no spec); the audit status from `stages.audit.artifacts` of the same entry: `final`, `open (<issues>)`, or "audit not run" when the stage is `skipped` or `pending`; one line "fixed by the audit: <fix_files>" when there are any;
   - subject text and body in the plan's language; the type and the scope stay as above.
5. **Confirmation.** With a confirmation channel, ask before committing when any of these holds, in one question that shows all of them with the subject: `fix_files` is not empty (show the list); `excluded` from step 3 holds a file the pipeline did not write (not `BACKLOG.md` and not a spec, plan, part, roadmap, review, report, completion, journal, diff report or follow-ups file of this goal; e.g. `docs/api.md` next to a plan in `docs/`): it stays out of the commit, so ask whether to commit without it; `<exec_dir>/state.json` (read only) has units that are `failed` or `pending`: the plan is not fully executed, ask whether to commit what the finished units did. Wait for an explicit "yes"; record it with `J journal-question <journal> --skill plan-executor --plan <P> --stage commit --text "<question>" --option "<yes>" --option "<no>" --answer "<answer>"`. "No" → `J journal-event <journal> --skill plan-executor --plan <P> --stage commit --status done --artifact declined=yes`, and stop. Without a confirmation channel (a chain run) the files are committed: the runner started this stage after the audit; the left-out files and unfinished units are named in the report (step 6).
6. **Commit.** `commit-run <exec_dir> --message-file <file> --journal <journal>`. It refuses before touching the index, at the first failing check in this order: `no-git` → `baseline-head-unknown` → `index-not-empty` → `snapshots-missing` → `run-incomplete` → `failed-attempt` → `head-moved` → `mixed-files` → `foreign-changes` → an empty set (`empty: true`) → `bad-subject`:

   | Result | Action |
   |---|---|
   | `ok`, `empty: false` | the script recorded the commit in the journal; `J journal-event … --stage commit --status done`; report `sha`, `subject` and `files`. Also report, when not empty: `excluded` (run files left out as pipeline artifacts), with `excluded_outside_chain` singled out: project files left out only because of the plan's folder or a broad name pattern (also a `*-chain.json` that is not the run's journal, e.g. `config/supply-chain.json`), which stay uncommitted (the engineer commits them by hand); and `incomplete` (units `failed` or `pending`: the plan is not fully executed; a warning, not a refusal) |
   | `ok` with `journal_error` | the commit is made but not in the journal: say so, and record it once the journal works with `J journal-commit <journal> --plan <P> --sha <sha> --subject "<subject>" --file <file>...` (one `--file` per entry of `files`), then `--stage commit --status done` |
   | `ok`, `empty: true` | `J journal-event … --stage commit --status done --artifact empty=yes`; say there was nothing left to commit |
   | exit `2` `bad-subject` | fix the subject line of the message file and call `commit-run` again |
   | `index-not-empty` (`staged`) | the index already holds staged changes: the engineer commits or unstages them, then calls `commit` again; never unstage them yourself |
   | `mixed-files` (`files`) | these files had uncommitted work before the run that the run then changed: nothing is committed; the engineer commits them by hand or separates the changes |
   | `foreign-changes` (`files`) | the files changed outside the run after its last unit and are not audit fixes: accept them (`accept-changes <exec_dir> --note "<why>"`, then `commit-run` again) or stop |
   | `baseline-head-unknown` | the ledger is older than the commit stage: the engineer commits by hand; `<diffs>` lists the files |
   | `snapshots-missing` | the run's snapshots were pruned and garbage-collected: the engineer commits by hand; `<diffs>` lists the files. Only the expected tree is missing (the error names it and `accept-changes`): `accept-changes <exec_dir> --note "<why>"`, then `commit-run` again |
   | `run-incomplete` (`units`: id and status) | a unit is still `running` (the run was interrupted mid-unit): nothing is committed; finish or resume the run with `/plan-executor <plan>` first, then `commit` again |
   | `failed-attempt` (`files`) | a unit is `failed` and these files of the commit differ from the last done snapshot and are not audit fixes: the half-done attempt was not rolled back, or the files were changed outside the run: nothing is committed; restore only these files, `checkpoint-restore <repo> <restore_to> --paths <files> --exec-dir <exec_dir>` (`restore_to` of the failed unit's `unit-finish`: the last done snapshot), and `commit` again, or the engineer commits by hand. A full restore (without `--paths`) also throws away the audit's fixes: use it only when `fix_files` is empty |
   | `head-moved` (`baseline_head`, `head`) | `HEAD` is no longer on the line of the commit the run started from (another branch was checked out): nothing is committed; switch back to that branch, or commit by hand where the engineer wants it |
   | `commit-failed` | a hook failed and the index is restored: show the hook output; fix and call `commit` again, or stop. Never `--no-verify` |
   | `no-git` | `--status skipped --data '{"why": "no-git"}'` |

   For every row the engineer has to decide: with a confirmation channel, ask (the options of the row) and record it with `--answer`; without one, `J journal-question <journal> --skill plan-executor --plan <P> --stage commit --text "<the error and its files>" --option "<…>"...` (the stage becomes `stopped`), `J journal-export-findings <journal>`, and stop with a short report.
7. **After `done`.** Offer `checkpoint-prune <exec_dir>` to delete the run's snapshot refs.
