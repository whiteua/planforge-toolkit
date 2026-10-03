# Changelog

PlanForge Toolkit is a rolling release: every push to `main` is a release, and `npx skills update`
replaces the installed files without a prompt. This file lists changes that alter behaviour or
break work in progress, newest first.

## 2026-10

The exact date is set at release.

Specs and plans written before this release keep working: where a skill asked a question, it still
asks, and most new checks only warn on them. Two errors also hit old files: a task over 150 lines of
code without a `**Size:**` line fails `plan-check`, and a malformed settings line above `# Goal`
(`> chain:`, `> Chain :`) fails `spec-check` (see Breaking changes). Otherwise new errors come only
from new fields that are filled in.

### Breaking changes

**`plan-check` fails a task over 150 lines of code without a `**Size:**` line.** It used to warn
only. Split the task or add `**Size:** <N> lines — <reason>` after its `Files` block. This applies
the next time `plan-check` runs on the plan; `plan-executor` does not re-check plans.

**`plan-executor` stops when files change between tasks.** When the working tree differs from what
the previous task left, `unit-begin` returns `reason: foreign-changes` with the paths instead of
starting the next task. Accept the changes (`accept-changes`), restore those files
(`checkpoint-restore --paths … --exec-dir …`) or stop. Hand edits between tasks now need this
decision; `BACKLOG.md` is not compared.

**`unit-begin` returns `external` as objects** `{env, access, kind, consent, confirmed, source}`
instead of the raw `**External:**` lines. Tools that read the old strings must be updated.

**`plan-executor` commits on an explicit command.** `/plan-executor <plan> commit` (in a chain:
the commit stage after the audit) commits the run's files and the files the resolver fixed on your
branch, through `commit-run` and with your hooks. A manual run with audit fixes lists them and waits
for an explicit "yes". It refuses a non-empty index (`index-not-empty`), files that held your
uncommitted work before the run and were changed by it (`mixed-files`) and files changed outside the
run (`foreign-changes`). Push, amend, force and `--no-verify` are never used; without the command
nothing is committed, as before. `plan-resolver` still runs no git command that changes anything.

**Findings outside the plan go to `<goal>-followups.json`.** The executor no longer writes
`<plan>-followups.json`. Findings of the executor, the resolver and the revision are recorded once
in the chain journal (`journal-finding`), appended to `BACKLOG.md` at once, and exported to
`<goal>-followups.json` next to the spec. Tools that read the old file must read the new one.

**`checkpoint-restore --paths` takes paths from the repository root**, like `foreign-changes`,
instead of from the workdir. `--paths BACKLOG.md` alone fails with `paths-empty` (exit 2) instead of
restoring nothing; drive-relative (`C:cli.py`) and pathspec-magic (`:(glob)*.py`) paths fail with
`invalid-path`; a file equal to the snapshot is reported `unchanged`.

**`spec-check` fails on a malformed settings line.** A line above `# Goal` that looks like `Chain`,
`Environment`, `Backlog` or `Tier` but does not match the format (`> chain:`, `> Chain :`) is the
error `malformed-metadata`; `settings` returns it as a warning. Such lines used to be ignored.

**`backlog-append` refuses the user section.** `--section "My notes"` (or `Свои заметки`, in any
case) fails with exit 1, and the user section is found regardless of case.

### Added

- Every skill talks to the user in the language of the first task statement: questions, answer
  options, gates and summaries (`detect-lang`; `lang` in `spec-check` and `plan-check`).
- Chain settings in the spec: `> Chain:`, `> Environment:` (with `read=` and `write=` rights) and
  `> Backlog:` above `# Goal`. `plan-iterative-revision`, `plan-splitter`, `plan-executor` and
  `plan-resolver` read them instead of asking; a run without a confirmation channel and without a
  needed decision stops with a report. For an older spec `plan-writing` asks as before and writes
  the answers into the plan header.
- Separate consent for reading and for changes on each external system (`run`, `task`, `deny`);
  production changes are never allowed for a whole run. `**External:**` lines name the access:
  `(read)` or `(write)`. `plan-executor consent` records a consent given during a run; it is
  cleared on resume.
- `plan-executor`: `settings-drift` on resume when the source of the settings changed (continue
  with `--accept-drift`), `accept-changes`, `checkpoint-restore --paths` and `--exec-dir`.
  `BACKLOG.md` at the repository root no longer makes the working tree dirty for `ledger-init`
  (the skills append to it between runs).
- Shared `BACKLOG.md` at the repository root: Out of Scope items of approved specs and findings of
  the executor and the resolver outside the plan. `/plan-brainstorming BACKLOG.md` takes the
  unchecked items as the next task. Several specs of one goal are numbered `<root>-1-spec.md`,
  `<root>-2-spec.md` by default.
- `plan-check` returns `settings`, `task_count`, `plan_bytes`, `lang` and `oversized` (tasks with a
  `**Size:**` line); `plan-iterative-revision` reports an unjustified oversized task as `minor`.
- `plan-resolver`: `assert-readonly` accepts several allowed paths (report and `BACKLOG.md`); with
  `read=run` the audit re-checks tasks marked `External (read)` itself.
- Chain journal `<goal>-chain.json` next to the spec, kept by every skill, manual runs included.
  Each plan has the stages `writing`, `revision`, `split`, `execution`, `diffs`, `audit` and
  `commit` with checked transitions; a run without a confirmation channel records its question
  (`Qn`) and stops, and the next run applies the answer and continues. `brainstorm_tool.py` gained
  `journal-path`, `journal-event`, `journal-unit`, `journal-question`, `journal-answer`,
  `journal-finding`, `journal-commit`, `journal-export-findings`, `journal-show`,
  `journal-reconcile` (statuses from the artifacts after a crash, `--rebuild` for a corrupt
  journal) and `journal-validate`. Without `plan-brainstorming` beside it a skill works without a
  journal.
- `plan-executor`: `<base>-diffs.md` next to the plan after the run (`run-diff --markdown`: a file
  table and one `diff` block per file, pipeline artifacts excluded); `ledger-path` (read-only),
  `commit-run` and the `commit` mode; the ledger stores `baseline_head` and the journal path, and
  `unit-begin` / `unit-finish` write the unit events. Without git the diff report and the commit are
  skipped.
- `plan-resolver` records the files its fix phase changed (`fix_files`) in the journal, and its
  closing gate names `/plan-executor <plan> commit`.
- `plan-check` and the revision's `bootstrap` return `journal`; `record` returns `journal_event`.
- New skill `plan-chain-runner`: after one start dialogue (graph of the specs, models per role,
  chain settings, environments, an optional start commit) it runs the approved specs of one goal
  through writing, revision, split, execution, audit and commit, schedules them by their
  dependencies, launches agents with the model of each role on Claude Code, GitHub Copilot CLI or in
  one session, reports progress and ETA, stops with questions in the chain journal and resumes with
  `continue` / `discuss` (`продолжить` / `обсудить`). Its scheduler is `chain_tool.py`; models
  per role live in `~/.planforge/runner.json`.
- `help` as the only argument of any pipeline skill shows its `USAGE.md` in the dialogue language;
  `/plan-chain-runner help` shows the pipeline map.
- `plan-brainstorming` amend mode: given an approved spec, it discusses only the change, edits the
  spec in place and re-checks it; the journal turns the change into a `drift` question for the plan.
- `journal-validate` accepts the optional `runner` section of the journal (types, graph specs, no
  cycles).
- Fixes: a `> **Source:**` line and a link target in `<…>` are read in roadmaps and parts;
  `**External:**` lines inside code blocks no longer count; `backlog-append` keeps the file mode of
  `BACKLOG.md` and writes to the target of a symlinked `BACKLOG.md`.
- `plan-brainstorming` checks off the `BACKLOG.md` items an approved spec took in (`backlog-mark`,
  only the checkbox byte changes); `[x]` means "taken into an approved spec", not "done", and
  unchecking stays with the user. `journal-question --spec` binds the plan entry that a question
  creates before `plan-writing` to its spec. `settings-load` returns `pinned` per role: an alias
  (`sonnet`, `opus`, `haiku`, `fable`) does not pin the version, a full model id does, and such a
  role runs through its agent definition file.
- `BACKLOG.md` items have three states: `[ ]` open, `[x]` taken into an approved spec, `[-]`
  cancelled by the user. `backlog-parse --state open|done|cancelled|all` (default `open`, as before)
  gives each item a `state`; `backlog-append` no longer appends a cancelled item again (the
  duplicate key ignores the `Отменено. ` / `Cancelled. ` prefix); `backlog-mark` refuses a `[-]`
  line (`cancelled`, exit 1). New `backlog-unmark` unchecks one item an amended or withdrawn spec
  no longer covers, and new read-only `backlog-sweep` gives `plan-brainstorming` the open items of a
  section and the specs of its chain journal: in backlog and amend mode it checks off, after you
  confirm, the items a spec already covers.

### Plans in progress

- Old specs and plans: nothing to do. Environments in the old form (without `read=` / `write=`) and
  `External` lines without `(read)` / `(write)` give warnings, not errors.
- A spec or plan header that already uses the new lines must be complete: an environment line
  without `read=` or `write=`, `write=run` on prod, or an `External (write)` on an environment with
  `write=deny` is an error. Change `write=run` on prod to `task` or `deny`.
- Finish `plan-executor` runs started with the previous version before updating, or start a new run
  in a new `exec_dir` after it.
- Tasks over 150 lines of code: split them or add a `**Size:**` line before re-running `plan-check`.
- Ledgers created before this release have no `baseline_head`: `commit-run` stops on them with
  `baseline-head-unknown`. Commit such a run yourself or start a new run.
- Nothing to migrate for the journal: the first skill that runs creates it. Old
  `<plan>-followups.json` files stay as they are and are not read.
- Journals without a `runner` section stay valid; `plan-chain-runner` adds it at its start.
- A journal with a time field that is not `YYYY-MM-DDTHH:MM:SSZ` (`created_at`, `*_at`, `at`) now
  fails `journal-validate`, and `plan-chain-runner` stops on it with `journal-corrupt`: set the
  field by hand (`null` only where the journal format allows it). `--spec` of `journal-event` or
  `journal-question` that differs from the spec of the plan's entry now fails with
  `journal-plan-unknown`.

## 2026-09-30

A refactor of the whole pipeline. Finish or restart plans that are in progress before updating.

### Breaking changes

**Split plans are renamed.** `plan-splitter` now writes `<base>-roadmap.md` and parts
`<base>-a.md`, `<base>-b.md`, … (`aa`, `ab` after `z`). The old `<base>-stg00-roadmap.md` /
`<base>-stgNN.md` files are rejected by `plan-executor`, `plan-iterative-revision` and
`plan-resolver` (`invalid-stage-id`). Re-run `plan-splitter` on the source plan; the old files can
be deleted.

**External systems need your permission in the plan.** A plan whose steps reach a database, API or
remote service lists each environment in its header under `**Environments:**` with your permission
quoted verbatim, and marks the tasks that use it with `**External:**`. `plan-check` rejects a plan
that names a listed environment without these lines, and `plan-executor` asks before running such
a task. Plans written before this date have no such block: add it, or the executor runs those
steps without asking.

**`plan-executor` refuses a ledger in the temp directory.** `ledger-init` fails with
`exec-dir-ephemeral` when `exec_dir` is inside the OS temp dir. Use `auto` (it resolves to
`<repo parent>/.exec/<repo>-<plan>/`) or pass `--allow-temp` for a throwaway run.

**`plan-executor` no longer commits.** Per-unit snapshots live in hidden refs
`refs/plan-executor/<run>/<unit>`; nothing is committed on your branch. Commits named
`[plan-executor] task-N-done` come from the previous version.

**`plan-resolver` reports are stricter.** Every closed task needs evidence: an anchor
`path#Lx-Ly` that points at existing lines, or, for a checkpoint or manual verification,
`evidence_probe: <command> → <result>`. `validate-report --root` checks the anchors against the
code. Reports written by the previous version may fail validation as final reports; run a new
audit pass.

**`plan-resolver` commands changed.** `iteration-check` is removed; the stuck-open gate is in
`bootstrap` (`stuck_open`). The reference files were merged: `BOOTSTRAP`, `FINGERPRINT`, `TOOLING`,
`STATUS-RULES`, `PASS-FIRST`, `PASS-SUBSEQUENT`, `CODE-TRACING`, `ERROR-TAXONOMY` and `PROBES` are
now `WORKFLOW`, `AUDIT`, `REPORT-FORMAT` and `FIX-LOOP`.

**`plan-iterative-revision` result changed.** The `cache_hits` field is gone from the result JSON,
`stop_reason` gained `unchanged`, and `references/WORKFLOW.md` and the review templates were
removed (the script renders review files). Stop gates count only the reviews of the current run.

**`plan-brainstorming` references changed.** `plan-lifecycle.md` was merged into
`spec-contract.md`.

### Added

- `plan-iterative-revision` verifies every part of a split plan in one run when given the roadmap
  (`/plan-iterative-revision <base>-roadmap.md`), with one review trail per part.
- `plan-splitter` deep verification is one batch run with a machine gate (`verify-status`).
- `plan-executor`: `run-diff` (what the run changed), notes for deviations agreed with the
  engineer, a follow-ups file for out-of-scope findings, lighter gates for checkpoint,
  documentation-only and test-only tasks.
- `plan-resolver`: `fix` / `next` / `auto` modes repair the code from the report and re-audit.
- `plan-writing`: `plan-check --root` checks that the files a plan relies on exist; plans record a
  test baseline and cite existing code as `path:line`.
- The visual companion of `plan-brainstorming` works on Windows with Git Bash.
- Skill instructions are in English; output templates stay paired in Russian and English.
