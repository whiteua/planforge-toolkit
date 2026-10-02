# plan-resolver — Quick Reference

Audit how well a plan was implemented in the code and write a report with findings. Audit mode
never modifies code or the plan; `fix`/`next`/`auto` also repair the code from the report and
re-audit (the plan is never modified).

## How to Invoke

```
/plan-resolver <plan-path> [report-1-path] [report-2-path] ...   # audit
/plan-resolver [plan-path] fix                                     # one fix → re-audit cycle
/plan-resolver [plan-path] next                                    # same as fix; continue after auto stops
/plan-resolver <plan-path> auto [limit]                            # audit → fix → audit loop, limit default 2
```

### Usage Examples

```bash
# First pass — no prior reports yet
/plan-resolver docs/plans/plan01-impl.md

# Second pass — list previous reports in order for delta analysis
/plan-resolver docs/plans/plan01-impl.md docs/plans/plan01-impl-report-1.md

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

## What Happens

```
Audit pass
1. BOOTSTRAP      — validate the plan and reports, next report number (exit 64: plan already closed)
2. PREFLIGHT      — the report file can be created
3. FINGERPRINT    — workspace snapshot before the audit
4. AUDIT          — trace every task and known issue to real code lines (read-only probes allowed)
5. WRITE REPORT   — exactly one new report; defects outside the plan also go to BACKLOG.md (backlog-append)
6. CENSUS + VALIDATE — every plan task covered; structure, statuses and evidence anchors verified against the code
7. ASSERT-READONLY — nothing but the report and BACKLOG.md changed
8. NEXT ACTION    — status, counts, suggested command

Fix cycle (fix / next / auto)
1. DISCOVER       — reports of the plan; closed → stop, none → audit first
2. OPEN-ISSUES    — open issues, critical → low
3. PROTECT        — plan and reports hashed; fix-start snapshot
4. FIX            — minimal code changes per issue (applied / needs-user / skipped)
5. DIFF           — changed files from the snapshot diff, plan and reports untouched
6. MARK-FIX       — outcome per issue in the report's Fix Log
7. AUDIT          — subsequent pass → next report
8. CYCLE-CHECK    — complete / ask-user / stop-stalled / stop-limit / continue (auto)
```

Code changes stay uncommitted in the working tree for your review.

## Report Types

| File | When | Meaning |
|---|---|---|
| `<base>-report-N.md` | issues or open tasks remain | open report |
| `<base>-report-N-final.md` | every task ✅/not-applicable, no open issues | closing report |

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
never writes any other file except appended lines of `BACKLOG.md` at the repository root
(`backlog-append`); never delegates fixes to other skills.

## Prerequisites

- Python ≥ 3.8 in PATH
- The codebase where the plan was executed, readable; the plan directory writable

## Common Errors

| Symptom | Cause | Fix |
|---|---|---|
| Exit 64: plan already closed | A `-final.md` report exists | Nothing to do |
| Preflight failed | The next report name already exists | Check numbering; list all existing reports |
| `anchor file not found` / `beyond end of file` | A report cites code that is not there | The audit must cite real lines; fix the report |
| `task-census-no-units` | The plan has no recognisable tasks | Use a plan with task headings |
| `probe-mutated-workspace` | Something changed files during the audit | Review the changes; re-run |
| Warning: closed on the executor's report | A task needs an external system the audit may not touch | Re-verify it yourself on a permitted environment, or accept the executor's recorded result |
| `auto` stopped: ask-user | Remaining issues need a decision | Answer, update the plan if needed, re-run |
| `auto` stopped: stop-stalled | A cycle closed nothing | Check the Fix Log; fix manually |
| `auto` stopped: stop-limit | Issues remain after the limit | Review, then `/plan-resolver next` |

## Pipeline Position

```
plan-brainstorming → plan-writing → plan-iterative-revision → plan-splitter → plan-executor → [YOU ARE HERE]
```

**Previous:** `plan-executor` (its hand-off names the master plan and any units it did not finish)
**Next:** none; fix with `fix`/`auto` or by hand and re-run
