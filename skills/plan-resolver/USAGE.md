# plan-resolver — Quick Reference

Audit how well a plan was implemented in code. Produces a report with findings. The default audit mode never modifies code or the plan; `fix`/`next`/`auto` modes also repair the code from the report and re-audit (the plan is never modified).

## How to Invoke

In VS Code Copilot chat, type:

```
/plan-resolver <plan-path> [report-1-path] [report-2-path] ...   # audit
/plan-resolver [plan-path] fix                                     # one fix → re-audit cycle
/plan-resolver [plan-path] next                                    # same as fix; continue after auto stops
/plan-resolver <plan-path> auto [limit]                            # audit → fix → audit loop, limit default 2
```

### Usage Examples

```bash
# First pass — no prior reports exist yet
/plan-resolver docs/plans/plan01.md

# Second pass — supply previous reports for delta analysis
/plan-resolver docs/plans/plan01.md docs/plans/plan01-report-1.md

# Third pass — with all prior reports in order
/plan-resolver docs/plans/plan01.md docs/plans/plan01-report-1.md docs/plans/plan01-report-2.md

# Plan in a custom directory
/plan-resolver .docs/.plans/refactor/plan.md .docs/.plans/refactor/plan-report-1.md

# Fix issues from the latest open report, then re-audit (reports are discovered automatically)
/plan-resolver docs/plans/plan01.md fix

# Fully autonomous: audit, fix, re-audit — up to 2 fix cycles, then stop
/plan-resolver docs/plans/plan01.md auto

# auto stopped with open issues → one more manual cycle
/plan-resolver next
```

**Important:** In audit mode the full `plans-list` must be provided explicitly — list the reports in order after the plan path. In `fix`/`next`/`auto` the reports are discovered next to the plan; without a plan path, `fix`/`next` use the plan from the conversation or the single plan whose latest report is open.

## Arguments

| Argument | Required | Description |
|---|---|---|
| Plan path | **Yes** | Path to the master plan (first in the list) |
| Previous reports | No | Audit mode: paths to previous report files (subsequent passes use them for delta analysis) |
| `fix` / `next` | No | Fix the latest open report's issues in code, then re-audit once |
| `auto [limit]` | No | Loop audit → fix → audit until `-final` or `limit` fix cycles (default 2) |

## What Happens

```
1. BOOTSTRAP — parse plans-list, determine next report number (N+1)
   → If plan already closed (exit 64): stop, nothing to do
2. PREFLIGHT — verify report file can be created
3. FINGERPRINT — snapshot workspace state before audit
4. AUDIT — trace plan tasks/phases against actual code
5. WRITE REPORT — exactly one new report file
6. VALIDATE — structural check of the report
7. ASSERT-READONLY — verify no workspace files were mutated
8. ITERATION-CHECK — suggest next action
```

Fix cycle (`fix` / `next` / `auto`):

```
1. DISCOVER — find the plan's reports; closed → stop, none → audit first
2. OPEN-ISSUES — open issues of the last report, ordered critical → low
3. PROTECT — hash the plan and all reports
4. FIX — minimal code changes per issue (applied / needs-user / skipped)
5. ASSERT-PROTECTED — plan and reports unchanged
6. MARK-FIX — record each outcome in the report's "Fix Log" section
7. AUDIT — standard subsequent pass → next report
8. CYCLE-CHECK — complete / continue (auto) / stop-limit / stop-stalled / ask-user
```

Code changes stay uncommitted in the working tree for your review.

## Report Types

| Type | When | Meaning |
|---|---|---|
| `<base>-report-N.md` | Issues found | Open report with findings |
| `<base>-report-N-final.md` | All tasks ✅, no errors | Closing report — plan is done |

## First Pass vs Subsequent Pass

| Pass | Input | Focus |
|---|---|---|
| First (no prior reports) | Master plan only | Full scan of all tasks against code |
| Subsequent (has prior reports) | Plan + last report | Delta: what was fixed, what remains, what regressed |

## Task Statuses in Reports

| Status | Meaning |
|---|---|
| ✅ | Correctly implemented |
| ⚠️ | Partially implemented or minor issues |
| ❌ | Not implemented or critically wrong |
| N/A | Not applicable (e.g., deprecated by later decisions) |

## Forbidden Actions

The resolver **never**:
- Edits the plan
- Edits previous reports, except the "Fix Log" section written by `mark-fix`
- Edits code during an audit pass (only the fix phase changes code)
- Runs installers, migrations, project-wide formatters, or git-mutating commands
- Creates more than one report per audit pass or overwrites an existing report file
- Auto-invokes other skills to fix issues

## Prerequisites

- Python ≥ 3.8 in PATH (for `scripts/resolver_tool.py`)
- Codebase accessible for read-only inspection
- File write tools available for creating the report

## Checklist Before Invoking

- [ ] Plan execution is complete (all tasks attempted)
- [ ] Provide the full plans-list: plan + all previous reports in order
- [ ] Workspace is the same codebase where the plan was executed
- [ ] Report directory is writable

## Common Errors

| Symptom | Cause | Fix |
|---|---|---|
| "Exit 64: plan already closed" | A `-final.md` report already exists | Nothing to do — plan is verified |
| "Cannot create report file" | Write tools unavailable | Enable file write mode |
| "Preflight failed" | Report file already exists | Check numbering; provide all existing reports |
| Report shows ❌ on tasks you completed | Code doesn't match plan expectations | Fix code and re-run resolver, or run `fix` |
| `auto` stopped: stop-limit | Issues remain after the cycle limit | Review changes, then `/plan-resolver next` |
| `auto` stopped: stop-stalled | A cycle closed no issues | Check the report's Fix Log and fix manually |
| `auto` stopped: ask-user | Remaining issues need a decision (plan conflict, design choice) | Answer, update the plan if needed, re-run |

## Pipeline Position

```
plan-brainstorming → plan-writing → plan-iterative-revision → plan-splitter → plan-executor → [YOU ARE HERE]
```

**Previous:** `plan-executor` (implements the plan)  
**Next:** (none — this is the final verification step; use `fix`/`auto` or fix manually and re-run)
