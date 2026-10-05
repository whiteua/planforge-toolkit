# Audit Pass

How one AUDIT pass reads the plan, traces it to the code and decides statuses. The pass type comes
from `bootstrap.pass_type`: `first`, `subsequent` (incremental or full, by `rescan-scope`) or
`subsequent-full` (the user's `full`: always the full pass).

## First pass (`first`)

1. Read the plan's skeleton, not the plan: `PT skeleton MASTER_PLAN` ([WORKFLOW.md](WORKFLOW.md),
   Notation). Redirect its stdout to a UTF-8 file in the OS temp dir (outside the workspace, never
   in the plan's folder) and Read that file in chunks (offset and limit) to its end: shell output
   is cut at about 30000 characters and the skeleton of a large plan is longer, so a skeleton
   taken straight from stdout may miss tasks. It keeps the header, every task heading, `Files`,
   `Preconditions`/`Postconditions`/`Done when`, `External`, `Size`, the step headings and
   `Run:`/`Expected:` lines, and puts one `[code <lang>, <N> lines: <signatures>]` line in place of
   each code block: the plan's code is context, not an actionable task, and the code that counts
   is read in the repository. Open a task in full with `PT task MASTER_PLAN <id>` (one task is
   short: print it directly) when its verdict comes out `partial`, `ambiguous` or `deviates`, and
   for a task without a `Files` block. Without `plan-writing` next to this skill (no `PT`, or `PT`
   exits `2` with `plan-brainstorming not installed alongside`), read `MASTER_PLAN` in full and
   say so in one line of the human gate.
2. Enumerate phases and tasks: `##`/`###` headings such as `Phase 1`, `Stage 1`, `Task 1.2`,
   `1.` become units; nested lists and sub-headings become tasks `<phase>.<sub>`; a plain-text plan
   becomes phase `1` with line tasks. On a skeleton there are no plan line numbers: identify a unit by its id and heading, and take its exact lines with `PT task MASTER_PLAN <id>`; when the plan is read in full, keep line numbers so evidence stays checkable. `task-census`
   applies the same rule: in plans with `Task` headings or a roadmap table, numbered prose lines are
   steps, not units.
3. Trace every actionable task to the code (below) and give it a verdict.
4. Record issues only for real implementation risks: a missing or wrong contract; broken business
   logic, formula or edge case; a wrong integration between modules; a security, auth or
   validation gap; a performance or ops risk the plan states explicitly; a failing read-only probe.
5. Resolve statuses ([REPORT-FORMAT.md](REPORT-FORMAT.md)). The first pass never closes a task
   without checkable evidence or with low confidence.
6. Write the report (`audit_scope: full`, `audit_tasks: all` from `report_header`), then
   `evidence-fingerprint` (WORKFLOW.md). `## Task` must be enough for an outside implementer: what
   to fix, where, how to verify.

If the caller (for example `plan-executor`'s hand-off) names units that were not completed, each of
them is either shown open (`⭕️`/`⚠️`) or closed with an anchor that proves the code is there.

What the hand-off adds is read from the executor's ledger (`exec_dir`), not from memory of the session:

- **Agreed deviations** (unit notes): check them against the code and describe them in
  `## Additional Context`; they are not `‼️ deviates`.
- **Checkpoint and verification tasks** leave no code: re-run the task's command when it is a
  permitted read-only probe and close the task with `evidence_probe: <command> → <result>`.
- **Settings**: `python "<SKILL_DIR>/../plan-brainstorming/scripts/brainstorm_tool.py" settings MASTER_PLAN`
  (`resolve_settings`: the plan header, else the spec named by the master plan's `**Spec:**`)
  gives the environments and their rights. Without `plan-brainstorming` next to this skill, or
  with `ok: false`, no environment is pre-approved.
- **Tasks that need an external system**: the audit does not go there without permission (Probes).
  A task whose `**External:**` line says `(read)` on an environment with `read=run` is
  re-verified by the audit itself with a read-only query and closed with
  `evidence_probe: <query> → <result>`, without `verification: executor-reported`. Every other
  external task (`(write)`, `read=task` or `read=deny`, no access kind) is closed on the
  executor's recorded result with `evidence_probe: …` and `verification: executor-reported`, and
  listed in the human gate as not re-verified.
- **Environments**: a step that ran on an environment the plan or its spec does not list with the
  user's quoted permission, or on production when only a test environment is permitted, is an
  issue (`ops`, `high`), even when its result was correct.

## Subsequent pass (`subsequent`, `subsequent-full`)

`subsequent`: right after the start fingerprint run `TOOL rescan-scope <plan> <LAST_REPORT>
--snapshot <start-json>` and save its JSON in the OS temp dir. `scope: incremental` → the
incremental pass; `scope: full` (`plan-changed`, `no-evidence-fingerprint`, `ratio`) → the full
pass. `subsequent-full` skips `rescan-scope` and always runs the full pass.

### Incremental pass

1. `TOOL carry-forward <LAST_REPORT> --scope <tmp>/scope.json --header <tmp>/bootstrap.json --out
   <bootstrap.next_open_path>`. The draft holds the frontmatter, every `carry` task with its
   evidence byte for byte, one stub `- <id>. <title> <!-- reaudit -->` per `reaudit` task, every
   issue of `LAST_REPORT` with its number (open ones marked `<!-- re-verify -->`), and
   `<!-- reaudit -->` in `## Additional Context` and `## Task`.
2. Read only the scope: each `reaudit` task by its `line_ranges` (Read with offset and limit; not
   the whole plan and not a skeleton), the code of `changed_files` and `missing_files`, and the
   files the task's anchors and `Files` name. Carried lines are neither re-read nor retyped.
3. Replace each stub with the task's status line and evidence (Code tracing below); a parent takes
   the worst marker of its children.
4. For each `<!-- re-verify -->` issue: re-audit it as in part A of the full pass and remove the
   marker; a closed issue stays as it is. New issues follow the old ones, numbered on; a carried
   issue keeps its title (`cycle-check` matches issues by title).
5. Write `## Additional Context` and `## Task` of this pass in place of their stubs.
6. Every task `✅` or `not-applicable` and no open issue: keep the open name and set
   `consecutive_open_invocations: 0`; only the following full pass may write `-final`.

`validate-report` rejects any marker left (`unfilled placeholder`). A change outside the evidence
files (a module an evidence file depends on) is invisible to this pass; the closing full pass sees
it.

### Full pass

A. Re-audit the known issues of `LAST_REPORT` (`parse-report`):

- check each carry-over issue's evidence against the current code and assign `✅ fixed`,
  `⚠️ fixed-with-errors`, `⭕️ not-fixed` or `⚠️ regressed`;
- a Fix Log entry (`applied`, `files: …`) says where to look, never that it is fixed: `✅ fixed`
  comes only from the code; `needs-user` issues carry over unchanged with the same `title`;
- an old issue without evidence gets `ambiguous-prev`, keeps its status and asks for a location;
- anchors from past reports are advisory: verify the lines before reusing them; a shifted or
  mismatching anchor is invalid and the verdict is derived again.

B. Re-scan the whole plan against the current code (first-pass steps 1-4: the skeleton, `PT task`
for a disputed task) and merge: vanished old
issues stay in the report as `✅ fixed`; persisting ones stay carry-over; new ones follow in
discovery order; regressions are reopened. Renumber issues from 1 in that order and keep carry-over
titles verbatim (`cycle-check` matches issues by title). Recompute phase and task statuses.

If the plan's SHA differs from `master_plan_sha256` in `LAST_REPORT`, continue and note in
`## Additional Context` that the plan changed between passes, so statuses were recomputed.

## Code tracing

On a first or full pass the items are the skeleton's lines: `Files`, the conditions, the step
headings, `Run:`/`Expected:` and the signatures of `[code …]` lines say what to look for; a
signature is a search hint, the evidence is the code in the repository.

From each item extract paths and directory names, `CamelCase`/`snake_case`/`kebab-case`
identifiers and constants, routes (`/api/...`), table/column/migration names, config and env names.

Search in this order: exact file or directory (Glob) → grep for exact identifiers → grep for
context keywords → read the matches → a read-only probe if the project already has one.

Evidence rules: every piece of evidence is `path#Lx-Ly` (1-based); more than 20 matches → narrow
with plan context; nothing found → write `not found`, never invent a file; conflicting
implementations → `ambiguous`. An unresolved plan reference is recorded as `AMBIGUOUS_REFERENCE`
at the nearest checkable anchor, not searched for across the whole plan.

Verdicts: `verified` (contract met, edge cases included), `partial`, `missing`, `deviates`
(trace exists, behaviour differs), `ambiguous`, `not-applicable` (no code needed).

Self-consistency: for blocking verdicts (`✅` on a critical task, `⭕️`, `‼️`) derive the verdict
once more from the same evidence; a mismatch downgrades the task to `⚠️ ambiguous`, and before the
next pass the evidence is strengthened (add a probe result, widen the anchor to the whole function,
cross-reference the covering test).

## Probes

Probes are extra checks, allowed only when read-only for the project. A probe is reading the repository and running local commands without side effects (build, offline tests, grep). Anything that reaches an external system — a database, an API, a remote service, a cloud account — even a constant query, runs only after the user explicitly allows it and names the environment. A permission covers the named environment only: never extend it to another one, and never treat an existing project script that targets another environment as permission. Production needs a separate confirmation for every action. Pre-approved reads (`read=run` in the spec's `> Environment:` line, production included) cover the plan's steps and the read-only checks of plan-iterative-revision and plan-resolver; changes on production are never pre-approved.

- Allowed: `python -m unittest`, `pytest`, `npm test -- --runInBand`, `go test`, `cargo test`,
  `dotnet test` when they write no tracked or generated files; static checks (`py_compile`,
  `tsc --noEmit`, `eslint` without `--fix`). Tool caches are excluded from the fingerprint
  ([WORKFLOW.md](WORKFLOW.md)), so `pytest` and friends do not trip the guard.
- Build: allowed when its output lands only in directories excluded from the fingerprint (`dist`,
  `build`, `out`, `target`, `bin`, `obj`, or paths in the root `.gitignore`), so tests run on a
  fresh build; `assert-readonly` catches a build that writes anywhere else. When a build is not
  possible, say in the report that previously built code was tested and close those tasks with
  `confidence: medium`.
- Forbidden: formatters and autofix (`black`, `ruff --fix`, `eslint --fix`, `prettier --write`,
  `go fmt`), installs and updates, generators and migrations, `git` mutations, anything interactive.
- Gate: an existing read-only probe for the touched area must be run and its exit code recorded in
  the evidence. Unrecognised commands (`npm run validate`, `cargo clippy`) are not run; the task gets
  `probe-needed`. The agent never writes a new probe. Verbs: run `test`, `check`, `lint`, `type`;
  never `migrate`, `seed`, `deploy`, `install`, `generate`, `git` (`build` only as described above).
- Recording: a failing probe becomes an issue only when tied to a plan task; write the command, exit
  code and a short stderr/stdout excerpt, not the full log.

## Issue levels and categories

| Level | Use when |
|---|---|
| `critical` | The plan cannot count as implemented: key contract missing, data-loss or security risk, workflow broken |
| `high` | Significant behaviour wrong or incomplete, workaround exists |
| `medium` | Local defect, edge case, missing test or validation that does not break the main path |
| `low` | Cosmetics, wording, maintainability without direct execution risk |

Categories: `logic`, `contract`, `code`, `tests`, `security`, `perf`, `ops`, `db`, `math`,
`code-plan-mismatch` (implemented, but not the behaviour the plan describes).

Every new issue names the affected task or phase, has evidence with files and lines or an honest
`not found`, says why it breaks the plan, gives an action-oriented recommendation, and carries a
severity that is not inflated.

## Defects outside the plan

A real defect noticed while tracing that no plan task covers is not an issue and does not change
any status. Describe it in `## Additional Context` (path, line, what breaks). After
`assert-readonly` (the journal end, WORKFLOW.md, Chain journal) record each one; the journal
appends it to the goal's section of the shared `BACKLOG.md` and exports it to
`<goal>-followups.json`:

`python "<SKILL_DIR>/../plan-brainstorming/scripts/brainstorm_tool.py" journal-finding <journal>
--skill plan-resolver --plan <P> --file <path from the repository root> [--line N]
--summary "<what is wrong>" --failure-scenario "<what breaks, and when>" --backlog-root <root>`

- `<root>` = `git -C <PLAN_DIR> rev-parse --show-toplevel`; outside git, the current working directory.
- `action: exists` (the same file and summary, e.g. from the previous pass) is fine: nothing is
  written twice.
- `backlog: failed` (with `backlog_error`): the finding is still recorded in the journal and goes
  into `<goal>-followups.json`; only its `BACKLOG.md` line is missing. Append that line by hand at
  the end of section `<S>` (`- [ ] <summary> (<path>:<line>) — plan-resolver, <plan file name>, <YYYY-MM-DD>`),
  change nothing else, and say so in the human gate. Exception: `backlog_error` starting with
  `user-section:` means `<S>` is the user's own section (`My notes` / `Свои заметки`, any case):
  it is never written, not even by hand; say so in the human gate instead.
- No journal but `plan-brainstorming` alongside (`journal-corrupt`): `backlog-append <root>
  --section <S> --source "plan-resolver, <plan file name>" --item "<path:line — summary>" --lang <bootstrap.language>`
  with the same script, also after `assert-readonly`. Exit `1` with `user-section:` writes nothing
  at all; any other exit `1` → by hand as above. The script missing: by hand as above.
- `<S>` = the journal's `goal`; without a journal, `backlog` of `brainstorm_tool.py settings <MASTER_PLAN>`;
  none → the plan file name without `.md` and `-impl` (the executor's rule).
