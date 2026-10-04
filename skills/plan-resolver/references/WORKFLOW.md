# Workflow

One AUDIT pass: a read-mostly audit of the master plan's implementation that creates exactly one new
report next to the plan. `fix`/`next`/`auto` wrap this pass in the fix loop ([FIX-LOOP.md](FIX-LOOP.md));
the invariants below hold for every AUDIT pass.

## Notation

- `WORKSPACE_ROOT`: the project root (the agent's cwd), passed to `bootstrap`.
- `MASTER_PLAN`: the plan; `PLAN_DIR` its directory; `REPORTS[]` its earlier reports;
  `LAST_REPORT` the newest one; `NEXT_REPORT` the report this pass writes.
- `plans-list`: `MASTER_PLAN` followed by `REPORTS[]` in order (audit mode: given by the user;
  other modes: from `discover`).

## Invariants

1. Writable files: the chosen `NEXT_REPORT` and `BACKLOG.md` at the repository root (append-only;
   defects outside the plan, [AUDIT.md](AUDIT.md)); outside the guard windows also the chain
   journal `<goal>-chain.json` and `<goal>-followups.json`, only through the `journal-*` commands
   of `brainstorm_tool.py` (Chain journal below).
2. `MASTER_PLAN` and `REPORTS[]` are read-only (the Fix Log is written only by `mark-fix`).
3. Project code is read-only in AUDIT: reading, grep/glob and read-only probes only. The tools
   cannot prevent a write; `assert-readonly` detects it afterwards and turns it into a blocker.
4. Preflight before the audit; start/current fingerprint around it; the only allowed diffs are
   `NEXT_REPORT` and `BACKLOG.md`.
5. One AUDIT pass = one report. Code fixes belong to FIX, never to AUDIT.
6. The report schema is [REPORT-FORMAT.md](REPORT-FORMAT.md); the language is `bootstrap.language`.
7. `task-census` must pass before hand-off: an uncovered task (exit 1) blocks the report.
8. `validate-report --root --plan` must pass: every evidence anchor points at existing lines, and
   only tasks without code files are closed by a command result (`evidence_probe`).
9. Every report carries its evidence fingerprint (`evidence-fingerprint`, after the report is
   written and before `validate-report`), and only a full pass writes `-final`. The JSON files of
   an incremental pass (`rescan-scope` output, the bootstrap header) live in the OS temp dir, like
   the snapshots.

## Command sequence

```text
bootstrap <workspace-root> <plan> [reports...] [--full]
preflight <plan-dir> <next-open-name> <next-final-name>
# journal start (Chain journal): journal-event … --stage audit --status running
fingerprint-workspace <workspace-root> <start-json>
# subsequent: rescan-scope <plan> <LAST_REPORT> --snapshot <start-json>   → <tmp>/scope.json
#   incremental: carry-forward <LAST_REPORT> --scope <tmp>/scope.json --header <tmp>/bootstrap.json --out <NEXT_REPORT>
# audit pass (AUDIT.md): first | incremental | full
# write NEXT_REPORT (incremental: fill the draft)
evidence-fingerprint <NEXT_REPORT> --snapshot <start-json> --plan <plan>
task-census <plan> <NEXT_REPORT>
validate-report <NEXT_REPORT> --root <workspace-root> --plan <plan>
fingerprint-workspace <workspace-root> <current-json> --base <start-json>
assert-readonly <start-json> <current-json> <NEXT_REPORT> <BACKLOG.md>
# journal end (Chain journal): journal-finding per defect outside the plan (AUDIT.md),
# journal-event … --stage audit --status done, journal-export-findings
```

## Bootstrap

`bootstrap` validates `plans-list`, computes the next report number and returns the header values.

- All paths must be inside `WORKSPACE_ROOT`. The plan may be `.md`, `.markdown`, `.txt`, `.text`.
- Reports are `<base>-report-<N>.md` / `<base>-report-<N>-final.md` in `PLAN_DIR`, `<base>` = plan
  file name without extension. Numbering is gapless (`bootstrap-gap-in-reports`,
  `bootstrap-duplicate-report`).
- A newest `-final` report means the plan is closed: exit `64`, `closed: true`, write nothing.
- Output: `master_plan*`, `plan_dir*`, `reports`, `last_report`, `next_n`, `next_open_name`,
  `next_final_name`, `next_open_path`, `next_final_path`, `language`, `pass_type`
  (`first` | `subsequent` | `subsequent-full` with `--full`; `--full` without earlier reports is
  ignored with the warning `--full ignored on the first pass`), `stuck_open` (below), and
  `report_header` with ready frontmatter values (`master_plan_path` relative to `PLAN_DIR`,
  `master_plan_sha256`, `master_plan_size`, `audit_iteration`,
  `consecutive_open_invocations_if_open` / `_if_final`, `previous_report_path`,
  `previous_report_sha256`, `language`, `audit_scope: full`, `audit_tasks: all`). Copy them; do
  not recompute.

## Fingerprint (read-only guard)

`fingerprint-workspace` walks `WORKSPACE_ROOT`, skips the root `.gitignore` patterns and the fixed
exclusions (`node_modules`, `.git/objects`, `__pycache__`, `dist`, `build`, `target`, `out`, `bin`,
`obj`, `.next`, `.gradle`, `.venv`, `venv`, plus tool caches: `.pytest_cache`, `.mypy_cache`,
`.ruff_cache`, `.hypothesis`, `.tox`, `.nox`, `.cache`, `.eslintcache`, `*.tsbuildinfo`), hashes every
file (SHA-256) and stores `files` + `stats` (`[size, mtime_ns]`) as JSON. With `--base <prev-json>`
(same root) files with unchanged size and mtime reuse the previous hash. More than 200 000 files →
stop and ask the user to narrow the scope.

Snapshot files live outside the workspace: `tempfile.mkstemp(prefix="fp-", suffix=".json",
dir=tempfile.gettempdir())`, close the fd, pass the path.

`assert-readonly <start> <current> <NEXT_REPORT> <BACKLOG.md>` allows exactly the paths given
after the two snapshots. Pass `BACKLOG.md` as an absolute path when it lies inside
`WORKSPACE_ROOT`; outside it is not fingerprinted, leave it out. Any other
added/removed/modified path is the blocker `probe-mutated-workspace`: rewrite the same report with
that single issue, run only `validate-report` again, stop with status OPEN. No second guard in the
same invocation.

`snapshot-diff <before> <after>` lists `added`/`removed`/`modified` paths and their union
`changed` (used by FIX). `.git/index` is excluded from the fingerprint, so read-only git commands
(`git status`, `git diff`) do not trip the guard; commits, resets and checkouts still do.

## Evidence fingerprint and pass scope

`evidence-fingerprint <report> --snapshot <start-json> --plan <plan>` writes the report's section
`## Evidence fingerprint` (`## Отпечаток улик` in a Russian report): one row `| path | SHA-256 |`
per evidence file, that is every anchor path of the stages section and of issue `evidence`, and
every file of the plan tasks' `Files` blocks (`brainstorm_tool.parse_plan_tasks`; a `Files` token
that names no file is skipped). The hashes come from this audit's start snapshot: the audit is
read-only, so they still hold at the end of the pass. A file the snapshot skips (`.gitignore`,
outside the root) is `excluded`, with a warning; an anchored file that does not exist is
`missing`. A second run replaces the section whole; it stands before the Fix Log, else at the end.
Without `plan-brainstorming` alongside only anchors count (warning `plan-files-unavailable`); a
snapshot of another workspace (the plan is not under its root) → exit `2` `snapshot-root-mismatch`.

`rescan-scope <plan> <LAST_REPORT> --snapshot <start-json> [--ratio 0.5]` compares that table with
the start snapshot of the current audit. Output: `changed_files`, `missing_files` (hashed before,
gone now), `unverified_files` (`excluded`/`missing` rows), `reaudit` (tasks whose anchors in the
last report or whose plan `Files` name a changed, gone or unverified file; tasks not `✅`;
`linked_items` of open issues; tasks closed by `evidence_probe` without an anchor; tasks new in the
plan; the parent of every re-audited subtask), `carry` (the other tasks of the report),
`audit_tasks` (`reaudit` without ids the plan does not have), `titles`, `line_ranges` (the plan
lines of each re-audited task), `issues`, `plan_sha_changed`, `scope` and `reason`. `scope: full`
when the plan's SHA-256 differs from the last report's `master_plan_sha256` (`plan-changed`), the
last report has no evidence section (`no-evidence-fingerprint`: a report older than this format) or
`reaudit` holds more than `FULL_SCOPE_RATIO = 0.5` of the tasks (`ratio`); otherwise
`incremental`, `reason: "<n> of <m> tasks touched"`. Save the JSON as `<tmp>/scope.json` in the OS
temp dir.

`carry-forward <LAST_REPORT> --scope <tmp>/scope.json --header <tmp>/bootstrap.json --out
<next_open_path>` writes the draft of the incremental report (`bootstrap.json`: the bootstrap
output or its `report_header`, in the OS temp dir too): the frontmatter with `audit_scope:
incremental` and `audit_tasks: [ … ]`, every `carry` task with its detail lines byte for byte, a
stub `- <id>. <title> <!-- reaudit -->` per `reaudit` task at its old indent, every issue block
with its number (open ones marked `<!-- re-verify -->`), and `<!-- reaudit -->` as the body of
`## Additional Context` and `## Task`; the validator warnings, the Fix Log and the evidence section
are not copied. Errors: `report-exists` (exit `2`: reports are immutable),
`inputs-inside-workspace` (exit `2`), `scope-mismatch` (exit `2`: the scope of another report),
`header-missing-fields` (exit `2`), `bad-input-json` (exit `2`), `use-full-pass` (exit `1`: the
scope is `full`, audit without a draft).

## Report name

`<base>-report-N-final.md` only after a full pass (`audit_scope: full`) when the issue list is
empty and every task is `✅` or `not-applicable` (`consecutive_open_invocations: 0`). An incremental
pass never writes `-final`: when it closes everything it keeps the open name with
`consecutive_open_invocations: 0` (it is not a stuck open report), and `cycle-check` answers
`full-audit-required`. Otherwise `<base>-report-N.md` with `consecutive_open_invocations_if_open`.

## Stuck open

`consecutive_open_invocations` counts open reports in a row (value ready in `report_header`).
`bootstrap.stuck_open` = `{consecutive_if_open, limit: 5, ask_required}`: when `ask_required` is
true and this pass also ends open, tell the user the audit keeps finding open issues and ask how
to proceed instead of proposing another pass. In `fix`/`next`/`auto`, `cycle-check` decides.

## Chain journal

`J` = `python "<SKILL_DIR>/../plan-brainstorming/scripts/brainstorm_tool.py"`. The journal
`<goal>-chain.json` records the `audit` stage of `MASTER_PLAN` for plan-executor's commit stage and
the chain runner. Its writes stay outside the guard windows: the start before the start
fingerprint, the end after `assert-readonly`, the FIX record after `snapshot-diff`. Without
`plan-brainstorming` alongside there is no journal: say so once and handle defects outside the plan
as AUDIT.md describes.

- `<journal>`, `P` = the `journal` and `plan` fields of `J journal-path MASTER_PLAN --create`. Every
  `--plan` below is `P`.
- **Start** (after `preflight`): `J journal-show <journal> --plan P`, stage `audit` (`unknown-plan`,
  exit `2`: no event of this plan yet, every stage is `pending`):
  - `skipped` (plan-executor recorded `resolver=skip`) → a skipped stage cannot be reopened: audit
    without stage events (no start, end or FIX record) and say so once; the findings are still
    recorded and exported.
  - open questions of stage `audit`, whatever its status (`stopped`, and also `done`:
    `journal-show` then gives the plan `next_action: answer`) → with a confirmation channel ask
    each and record `J journal-answer <journal> <Qn> --answer "<answer>"`; without one stop and
    name the ids. Answered questions: apply each, then `J journal-answer <journal> <Qn> --applied`,
    all before the stage moves to `running`.
  - `done` with `status=final` → the drift check: `J journal-reconcile <journal>`, then look in the
    journal file's `questions` for one of `P` whose text starts with `drift: audit` and that is not
    `applied` (the plan changed after the final audit). `open` → as the open questions above (the
    answer `rewrite` to audit the changed plan again, or `keep`); answered `rewrite` → the event
    below with `--reason drift`, and `J journal-answer <journal> <Qn> --applied` after the stage's
    `done` event; answered `keep` → `J journal-answer <journal> <Qn> --applied`, then
    `J journal-event <journal> --skill plan-resolver --plan P --stage audit --status done --input MASTER_PLAN`
    (the same status: it binds the stage to the current plan) and audit only if the user asks.
  - then `J journal-event <journal> --skill plan-resolver --plan P --stage audit --status running`;
    add `--reason audit-open` when the stage is `done` with `status=open` (a pass after an open
    report: `fix`, `next`, `auto`, or a new audit; the stored `status` decides, so never pass
    `--artifact status=open` to re-open the stage), `--reason drift` after an answered drift
    question, `--reason user-request` when it is `done` otherwise and the user asked for this
    audit. A stage already `running` (the FIX of this cycle started it) needs no event.
- **End** (after `assert-readonly`, also when the report became `probe-mutated-workspace`):
  1. each defect outside the plan: `J journal-finding … --skill plan-resolver …` (AUDIT.md);
  2. `J journal-event <journal> --skill plan-resolver --plan P --stage audit --status done --input MASTER_PLAN --artifact report=<NEXT_REPORT relative to the journal's directory> --artifact status=<open|final> --artifact issues=<number of open issues> --artifact scope=<full|incremental>` (`scope` = the report's `audit_scope`);
  3. `J journal-export-findings <journal>`.
- **FIX**: after `snapshot-diff` and `mark-fix` (FIX-LOOP.md), every path of `changed` becomes a
  repository-root path: `<prefix>` = `git -C <workspace-root> rev-parse --show-prefix` (empty at the
  repository root), then one command for all of them:
  `J journal-event <journal> --skill plan-resolver --plan P --stage audit --status running --artifact fix_files[]=<prefix><path> ...`
  (one `--artifact` per file; outside git, the paths as they are). plan-executor's `commit` stage
  commits exactly these files besides the run's own ones.
- **Questions without a confirmation channel**: `bootstrap.stuck_open.ask_required` with a report
  that stayed open, and the gates `ask-user`, `stop-stalled`, `stop-limit` and
  `full-audit-required` (FIX-LOOP.md; its decision is "run the closing full pass:
  `/plan-resolver <plan> full`"). In all five the last report is open and the `audit` stage is
  already `done`, and a question stops only a `running` stage: first
  `J journal-event <journal> --skill plan-resolver --plan P --stage audit --status running --reason audit-open`
  (no event when the stage is already `running`), then
  `J journal-question <journal> --skill plan-resolver --plan P --stage audit --text "<the decision needed>" [--option "<option>"]...`
  (the stage becomes `stopped`), then `J journal-export-findings <journal>`, and stop. With a
  confirmation channel the same question is asked and recorded with `--answer "<answer>"`.
- **Commit**: every human gate names `/plan-executor <MASTER_PLAN> commit`; it commits the run's
  files and `fix_files`. The resolver itself never runs a git mutation.
- **Errors**: `journal-corrupt` (exit `2`) → say it, propose `J journal-reconcile <journal> --rebuild`,
  continue without the journal; `journal-locked` (exit `1`) → repeat once; still locked: with a
  confirmation channel ask whether to continue without the journal, without one stop with a
  short report (no audit runs, so no `fix_files` go unrecorded); `journal-write-failed` (exit `1`,
  the file system refused the write, e.g. a read-only journal) → say it in one line with the error
  text and continue without the journal; `illegal-transition` → never force a status, say it in
  the gate; `open-questions: <ids>` (exit `1`, a `running` event, also with `--reason audit-open`,
  on a `stopped` stage that still has an open question of `P`) → stop on the open question: with a
  confirmation channel ask it and record `J journal-answer <journal> <Qn> --answer "<answer>"`,
  then repeat the event; without one stop and name the ids.

## Commands

```text
bootstrap <workspace-root> <plan> [reports...] [--full]
preflight <plan-dir> <next-open-name> <next-final-name>
fingerprint-workspace <root> <out-json> [--base <prev-json>]
evidence-fingerprint <report> --snapshot <start-json> --plan <plan>
rescan-scope <plan> <last-report> --snapshot <start-json> [--ratio 0.5]
carry-forward <last-report> --scope <json> --header <json> --out <report>
snapshot-diff <before-json> <after-json>
assert-readonly <start-json> <current-json> <allowed-path>...
parse-report <report.md>
validate-report <report.md> [--root <workspace-root>] [--plan <plan>]
task-census <plan> <report>
discover <workspace-root> [plan]
open-issues <report>
protect <out-json> <path>...
assert-protected <snapshot-json>
mark-fix <report> <issue-id> applied|needs-user|skipped [--files F...] [--note TEXT]
cycle-check <prev-report> <new-report> <cycle> [limit=2]
```

Exit codes: `0` ok; `1` the check ran and the contract is violated (`validate-report`,
`assert-readonly`, `assert-protected`, `task-census`, `mark-fix`, `preflight` target exists,
`discover` without exactly one candidate, `carry-forward` with a `full` scope); `2` bad input or
filesystem; `64` `bootstrap` found a `-final` report.

`task-census` exit `2` with `task-census-no-units` means the plan has no recognisable task units
(no headings, numbered items, bullets or a roadmap table): stop and ask the user for a structured
plan; do not hand-write a census.
