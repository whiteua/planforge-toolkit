# plan-resolver — Quick Reference

Audit how well a plan was implemented in the code and write a report with findings. Audit mode
never modifies code or the plan; `fix`/`next`/`auto` also repair the code from the report and
re-audit (the plan is never modified).

## How to Invoke

```
/plan-resolver <plan-path> [report-1-path] [report-2-path] ...   # audit
/plan-resolver <plan-path> [report-1-path] ... full                # audit, always a full pass (closes after an incremental one)
/plan-resolver [plan-path] fix                                     # one fix → re-audit cycle
/plan-resolver [plan-path] next                                    # same as fix; continue after auto stops
/plan-resolver <plan-path> auto [limit]                            # audit → fix → audit loop, limit default 2
/plan-resolver help                                                # show this quick reference in the dialogue language, nothing else
```

### Usage Examples

```bash
# First pass — no prior reports yet
/plan-resolver docs/plans/plan01-impl.md

# Second pass — list previous reports in order for delta analysis
/plan-resolver docs/plans/plan01-impl.md docs/plans/plan01-impl-report-1.md

# Closing full pass after an incremental one (cycle-check: full-audit-required)
/plan-resolver docs/plans/plan01-impl.md docs/plans/plan01-impl-report-1.md docs/plans/plan01-impl-report-2.md full

# Fix the issues of the latest open report, then re-audit (reports discovered automatically)
/plan-resolver docs/plans/plan01-impl.md fix

# Fully autonomous: audit, fix, re-audit — up to 2 fix cycles
/plan-resolver docs/plans/plan01-impl.md auto

# auto stopped with open issues → one more cycle
/plan-resolver next
```

In audit mode list the plan first and then every previous report in order. In `fix`/`next`/`auto`
the reports are discovered next to the plan.

## Arguments

| Argument | Required | Description |
|---|---|---|
| Plan path | **Yes** (optional for `fix`/`next`) | The master plan; for a split plan, the original `<base>.md`, not the roadmap |
| Previous reports | No | Audit mode: earlier report files in order |
| `fix` / `next` | No | Fix the latest open report's issues in code, then re-audit once |
| `auto [limit]` | No | Loop audit → fix → audit until `-final` or `limit` fix cycles (default 2) |
| `full` | No | Audit mode, last token: a full pass even where `rescan-scope` would choose an incremental one; after an incremental pass only a full one may write `-final` |

## What Happens

```
Audit pass
1. BOOTSTRAP      — validate the plan and reports, next report number (exit 64: plan already closed)
2. PREFLIGHT      — the report file can be created; the chain journal marks the audit stage running
3. FINGERPRINT    — workspace snapshot before the audit (git-tracked changes from git status with blob hashes; only the plan folder's ignored files hashed one by one; without git a walk filtered by the root .gitignore, origin: walk)
4. SCOPE          — later passes: rescan-scope compares the last report's evidence fingerprint with the evidence files hashed now → incremental or full
5. AUDIT          — full: trace every task and known issue to real code lines; incremental: carry-forward drafts the report and only the tasks on changed evidence, open tasks and open issues are re-audited (read-only probes allowed)
6. WRITE REPORT   — exactly one new report; defects outside the plan go to its Additional Context; evidence-fingerprint adds the hashes of its evidence files
7. CENSUS + VALIDATE — every plan task covered; structure, statuses and evidence anchors verified against the code
8. ASSERT-READONLY — nothing but the report and BACKLOG.md changed: a moved HEAD (commit, reset, checkout) is the violation HEAD, and a changed file in the plan's folder is a violation even when git ignores it; ignored paths outside the plan's folder (probe caches, build output) are only noted in the report's Additional Context, and so is origin: walk (no git)
9. JOURNAL        — defects outside the plan → journal + BACKLOG.md (journal-finding); audit stage done with the report's status and scope and the artifact guard=<git|walk>; <goal>-followups.json rewritten
10. NEXT ACTION   — status, counts, suggested command; the commit command /plan-executor <plan> commit

Fix cycle (fix / next / auto)
1. DISCOVER       — reports of the plan; closed → stop, none → audit first
2. OPEN-ISSUES    — open issues, critical → low
3. PROTECT        — plan and reports hashed; fix-start snapshot
4. FIX            — minimal code changes per issue (applied / needs-user / skipped)
5. DIFF           — changed files from the snapshot diff, plan and reports untouched; recorded as the audit's fix_files in the journal
6. MARK-FIX       — outcome per issue in the report's Fix Log
7. AUDIT          — subsequent pass (incremental when the evidence allows, in the same session) → next report
8. CYCLE-CHECK    — complete / full-audit-required / ask-user / stop-stalled / stop-limit / continue (auto)
9. FULL PASS      — after full-audit-required: auto runs the closing full pass (a fresh subagent when available) while cycles remain; fix/next name /plan-resolver <plan> full
```

Code changes stay uncommitted in the working tree for your review. The resolver never commits:
`/plan-executor <plan-path> commit` commits the executor run's files together with these fixes
(it asks before committing the fixes).

## Report Types

| File | When | Meaning |
|---|---|---|
| `<base>-report-N.md` | issues or open tasks remain | open report |
| `<base>-report-N-final.md` | after a full pass: every task ✅/not-applicable, no open issues | closing report |

## Task Statuses

| Marker | Meaning |
|---|---|
| `✅` | implemented as specified; needs an evidence anchor `path#Lx-Ly`, or for a checkpoint / manual verification an `evidence_probe: <command> → <result>` |
| `⚠️` | partial, defective, or ambiguous |
| `⭕️` | missing |
| `‼️` | deviates from the plan |
| `not-applicable` | explanatory item, nothing to implement |

## Forbidden Actions

The resolver never edits the plan; never edits previous reports except the Fix Log via `mark-fix`;
never edits code during an audit pass; never runs installers, migrations, project-wide formatters or
git-mutating commands; never writes more than one report per pass or overwrites an existing one;
never writes any other file except appended lines of `BACKLOG.md` at the repository root and the
chain journal `<goal>-chain.json` with `<goal>-followups.json` (through `brainstorm_tool.py`, after
the read-only check); never delegates fixes to other skills.

## Prerequisites

- Python ≥ 3.8 in PATH
- The codebase where the plan was executed, readable; the plan directory writable
- `plan-brainstorming` installed alongside: the read-only guard (`fingerprint-workspace`, `assert-readonly`, `snapshot-diff`) uses its `worktree_snapshot`; without it they exit 1 with `snapshot-unavailable` and the audit does not start

## Common Errors

| Symptom | Cause | Fix |
|---|---|---|
| Exit 64: plan already closed | A `-final.md` report exists | Nothing to do |
| Preflight failed | The next report name already exists | Check numbering; list all existing reports |
| `anchor file not found` / `beyond end of file` | A report cites code that is not there | The audit must cite real lines; fix the report |
| `task-census-no-units` | The plan has no recognisable tasks | Use a plan with task headings |
| `probe-mutated-workspace` | Something changed files during the audit, or a commit or reset moved `HEAD` (violation `HEAD`) | Review the changes; re-run |
| Warning: closed on the executor's report | A task needs an external system the audit may not touch | Re-verify it yourself on a permitted environment, or accept the executor's recorded result |
| `auto` stopped: ask-user | Remaining issues need a decision | Answer, update the plan if needed, re-run |
| `auto` stopped: stop-stalled | A cycle closed nothing | Check the Fix Log; fix manually |
| `auto` stopped: stop-limit | Issues remain after the limit | Review, then `/plan-resolver next` |
| `use-full-pass` from `carry-forward` | `rescan-scope` chose a full pass (plan changed, old report, too many tasks touched) | Audit the whole plan; there is no draft |
| `unfilled placeholder` | A `<!-- reaudit -->` or `<!-- re-verify -->` marker is left in an incremental report | Fill the stub or re-verify the issue |
| `final report requires a full pass` | `-final` written after an incremental pass | Keep the report open; run the full pass (`full`) |
| `invalid fingerprint snapshot` | The snapshot is from before goal 05 (old format without `entries`) or is not a snapshot | Fingerprint the workspace again |
| `snapshot-root-mismatch` | The snapshot was taken of another workspace | Fingerprint this workspace |
| `snapshot-unavailable` | `plan-brainstorming` is not installed next to `plan-resolver` | Install it alongside: the guard uses its workspace snapshot |
| `snapshot-failed` | `git status` or `git hash-object` failed | Fix the repository (e.g. a stale lock file), re-run |

## Pipeline Position

```
plan-brainstorming → plan-writing → plan-iterative-revision → plan-splitter → plan-executor → [YOU ARE HERE] → plan-executor commit
```

**Previous:** `plan-executor` (its hand-off names the master plan and any units it did not finish)
**Next:** `/plan-executor <plan> commit` (commit the run and the fixes); open issues: fix with `fix`/`auto` or by hand and re-run
