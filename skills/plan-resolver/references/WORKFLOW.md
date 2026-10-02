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

1. Writable files: the chosen `NEXT_REPORT` and `BACKLOG.md` at the repository root (append-only,
   through `backlog-append`; defects outside the plan, [AUDIT.md](AUDIT.md)).
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

## Command sequence

```text
bootstrap <workspace-root> <plan> [reports...]
preflight <plan-dir> <next-open-name> <next-final-name>
fingerprint-workspace <workspace-root> <start-json>
# audit pass (AUDIT.md): first | subsequent
# write NEXT_REPORT
task-census <plan> <NEXT_REPORT>
validate-report <NEXT_REPORT> --root <workspace-root> --plan <plan>
# backlog-append per defect outside the plan (AUDIT.md)
fingerprint-workspace <workspace-root> <current-json> --base <start-json>
assert-readonly <start-json> <current-json> <NEXT_REPORT> <BACKLOG.md>
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
  (`first` | `subsequent`), `stuck_open` (below), and `report_header` with ready frontmatter values (`master_plan_path`
  relative to `PLAN_DIR`, `master_plan_sha256`, `master_plan_size`, `audit_iteration`,
  `consecutive_open_invocations_if_open` / `_if_final`, `previous_report_path`,
  `previous_report_sha256`, `language`). Copy them; do not recompute.

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

## Report name

`<base>-report-N-final.md` only when the issue list is empty and every task is `✅` or
`not-applicable` (`consecutive_open_invocations: 0`). Otherwise `<base>-report-N.md` with
`consecutive_open_invocations_if_open`.

## Stuck open

`consecutive_open_invocations` counts open reports in a row (value ready in `report_header`).
`bootstrap.stuck_open` = `{consecutive_if_open, limit: 5, ask_required}`: when `ask_required` is
true and this pass also ends open, tell the user the audit keeps finding open issues and ask how
to proceed instead of proposing another pass. In `fix`/`next`/`auto`, `cycle-check` decides.

## Commands

```text
bootstrap <workspace-root> <plan> [reports...]
preflight <plan-dir> <next-open-name> <next-final-name>
fingerprint-workspace <root> <out-json> [--base <prev-json>]
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
`discover` without exactly one candidate); `2` bad input or filesystem; `64` `bootstrap` found a
`-final` report.

`task-census` exit `2` with `task-census-no-units` means the plan has no recognisable task units
(no headings, numbered items, bullets or a roadmap table): stop and ask the user for a structured
plan; do not hand-write a census.
