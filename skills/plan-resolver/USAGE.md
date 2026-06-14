# plan-resolver — Quick Reference

Audit how well a plan was implemented in code. Produces a report with findings — never modifies code or the plan itself.

## How to Invoke

In VS Code Copilot chat, type:

```
/plan-resolver <plan-path> [report-1-path] [report-2-path] ...
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
```

**Important:** The full `plans-list` must be provided explicitly. The skill does NOT auto-discover reports — always list them in order after the plan path.

## Arguments

| Argument | Required | Description |
|---|---|---|
| Plan path | **Yes** | Path to the master plan (first in the list) |
| Previous reports | No | Paths to previous report files (subsequent passes use them for delta analysis) |

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
- Edits code, the plan, or previous reports
- Runs formatters, installers, migrations, or git-mutating commands
- Creates multiple reports per invocation
- Overwrites an existing report file
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
| Report shows ❌ on tasks you completed | Code doesn't match plan expectations | Fix code and re-run resolver |

## Pipeline Position

```
plan-brainstorming → plan-writing → plan-iterative-revision → plan-splitter → plan-executor → [YOU ARE HERE]
```

**Previous:** `plan-executor` (implements the plan)  
**Next:** (none — this is the final verification step; fix issues and re-run if needed)
