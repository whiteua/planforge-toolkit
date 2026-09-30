# Audit Pass

How one AUDIT pass reads the plan, traces it to the code and decides statuses. The pass type comes
from `bootstrap.pass_type`.

## First pass (`first`)

1. Read `MASTER_PLAN` in full. Code blocks and quotes are context, not actionable tasks.
2. Enumerate phases and tasks: `##`/`###` headings such as `Phase 1`, `Stage 1`, `Task 1.2`,
   `1.` become units; nested lists and sub-headings become tasks `<phase>.<sub>`; a plain-text plan
   becomes phase `1` with line tasks. Keep line numbers so evidence stays checkable. `task-census`
   applies the same rule: in plans with `Task` headings or a roadmap table, numbered prose lines are
   steps, not units.
3. Trace every actionable task to the code (below) and give it a verdict.
4. Record issues only for real implementation risks: a missing or wrong contract; broken business
   logic, formula or edge case; a wrong integration between modules; a security, auth or
   validation gap; a performance or ops risk the plan states explicitly; a failing read-only probe.
5. Resolve statuses ([REPORT-FORMAT.md](REPORT-FORMAT.md)). The first pass never closes a task
   without checkable evidence or with low confidence.
6. Write the report. `## Task` must be enough for an outside implementer: what to fix, where, how
   to verify.

If the caller (for example `plan-executor`'s hand-off) names units that were not completed, each of
them is either shown open (`⭕️`/`⚠️`) or closed with an anchor that proves the code is there.

## Subsequent pass (`subsequent`)

A. Re-audit the known issues of `LAST_REPORT` (`parse-report`):

- check each carry-over issue's evidence against the current code and assign `✅ fixed`,
  `⚠️ fixed-with-errors`, `⭕️ not-fixed` or `⚠️ regressed`;
- a Fix Log entry (`applied`, `files: …`) says where to look, never that it is fixed: `✅ fixed`
  comes only from the code; `needs-user` issues carry over unchanged with the same `title`;
- an old issue without evidence gets `ambiguous-prev`, keeps its status and asks for a location;
- anchors from past reports are advisory: verify the lines before reusing them; a shifted or
  mismatching anchor is invalid and the verdict is derived again.

B. Re-scan the whole plan against the current code (first-pass steps 1-4) and merge: vanished old
issues stay in the report as `✅ fixed`; persisting ones stay carry-over; new ones follow in
discovery order; regressions are reopened. Renumber issues from 1 in that order and keep carry-over
titles verbatim (`cycle-check` matches issues by title). Recompute phase and task statuses.

If the plan's SHA differs from `master_plan_sha256` in `LAST_REPORT`, continue and note in
`## Additional Context` that the plan changed between passes, so statuses were recomputed.

## Code tracing

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

Probes are extra checks, allowed only when read-only for the project.

- Allowed: `python -m unittest`, `pytest`, `npm test -- --runInBand`, `go test`, `cargo test`,
  `dotnet test` when they write no tracked or generated files; static checks (`py_compile`,
  `tsc --noEmit`, `eslint` without `--fix`). Tool caches are excluded from the fingerprint
  ([WORKFLOW.md](WORKFLOW.md)), so `pytest` and friends do not trip the guard.
- Forbidden: formatters and autofix (`black`, `ruff --fix`, `eslint --fix`, `prettier --write`,
  `go fmt`), installs and updates, generators and migrations, `git` mutations, anything interactive.
- Gate: an existing read-only probe for the touched area must be run and its exit code recorded in
  the evidence. Unrecognised commands (`npm run validate`, `cargo clippy`) are not run; the task gets
  `probe-needed`. The agent never writes a new probe. Verbs: run `test`, `check`, `lint`, `type`;
  never `migrate`, `seed`, `build`, `deploy`, `install`, `generate`, `git`.
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
