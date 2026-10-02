# Changelog

PlanForge Toolkit is a rolling release: every push to `main` is a release, and `npx skills update`
replaces the installed files without a prompt. This file lists changes that alter behaviour or
break work in progress, newest first.

## 2026-10

The exact date is set at release.

Specs and plans written before this release keep working: where a skill asked a question, it still
asks, and the new checks only warn on them. New errors come only from new fields that are filled in.

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

### Plans in progress

- Old specs and plans: nothing to do. Environments in the old form (without `read=` / `write=`) and
  `External` lines without `(read)` / `(write)` give warnings, not errors.
- A spec or plan header that already uses the new lines must be complete: an environment line
  without `read=` or `write=`, `write=run` on prod, or an `External (write)` on an environment with
  `write=deny` is an error. Change `write=run` on prod to `task` or `deny`.
- Finish `plan-executor` runs started with the previous version before updating, or start a new run
  in a new `exec_dir` after it.
- Tasks over 150 lines of code: split them or add a `**Size:**` line before re-running `plan-check`.

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
