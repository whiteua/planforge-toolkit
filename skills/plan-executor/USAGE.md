# plan-executor — Quick Reference

Execute a ready plan or staged roadmap one unit at a time with ledger-backed progress tracking, gates, and checkpoints.

## How to Invoke

In VS Code Copilot chat, type:

```
/plan-executor <plan-or-roadmap-path>
```

### Usage Examples

```bash
# Execute a single plan (with ### Task N: headings)
/plan-executor docs/plans/plan01-feature.md

# Execute a staged roadmap (processes stages in dependency order)
/plan-executor docs/plans/plan01-feature-stg00-roadmap.md

# Plan in a custom directory
/plan-executor .docs/.plans/refactor/plan-stg00-roadmap.md
```

## Arguments

| Argument | Required | Description |
|---|---|---|
| Plan/Roadmap path | **Yes** | Path to a plan `.md` or `-stg00-roadmap.md` file |

## Input Types

| Input | Detection | Behavior |
|---|---|---|
| Staged roadmap (`-stg00-roadmap.md`) | Has stage table + dependencies | Executes stages in dependency order |
| Whole plan (with `### Task N:` headings) | Has explicit task headings | Executes tasks sequentially |

## What Happens

```
BOOTSTRAP:
  detect-input → parse-roadmap/parse-tasks → ledger-init → checkpoint-detect
      ↓
EXECUTE LOOP (per unit):
  ledger-next → recommend-strategy → scope-context → mark running → execute unit → gate → checkpoint → mark done
      ↓
FINALIZE:
  All done → render progress → propose plan-resolver
```

## Execution Flow Details

1. **ledger-next** — picks the next executable unit (respects dependencies)
2. **recommend-strategy** — suggests isolation level and gate tier based on unit weight
3. **scope-context** — returns file paths relevant to the unit
4. **ledger-mark running** — claims the unit, increments attempt counter
5. **Execute** — agent implements exactly one unit (stage or task)
6. **Gate** — verify the unit is done (tests pass, artifacts exist)
7. **Checkpoint** — git commit as a savepoint
8. **Mark done** — `ledger-mark done`, render progress

## Gates and Retries

- Each unit gets **3 attempts** (1 primary + 2 retries)
- Identical failure signature → immediate STOP (no wasted retries)
- Gate cannot pass silently if tests are missing → escalation, not fake success

## Stop Conditions

| Condition | Action |
|---|---|
| All units done (`all-done`) | Finalize → propose resolver |
| 3 attempts exhausted on a unit | STOP with stop-report |
| Stagnation (same error repeats) | STOP with stop-report |
| All units blocked, no retryable | STOP with stop-report |
| Rollback needed | Ask engineer for decision |

## Output

- `<exec_dir>/state.json` — ledger (source of truth for progress)
- `<exec_dir>/progress.md` — human-readable progress report

`exec_dir` is located **outside the project repository** (typically sibling to plan files, e.g., `.docs/.plans/<name>/.exec/`). This ensures git operations in the workdir never affect the ledger.

## Prerequisites

- Git available (for checkpoints; without git, auto-rollback is unavailable)
- Plan/roadmap has been validated (ideally by iterative-revision)
- Working codebase accessible

## Checklist Before Invoking

- [ ] Plan or roadmap exists and is finalized
- [ ] Codebase is in a clean git state (no uncommitted work that could conflict)
- [ ] Dependencies/environment ready for the first task
- [ ] If staged: roadmap file points to existing stg-files

## Common Errors

| Symptom | Cause | Fix |
|---|---|---|
| "No units found" | Plan has no `### Task N:` headings | Check plan format; re-run plan-writing |
| "Attempts exhausted" | Implementation failed 3 times | Read stop-report, fix manually, restart |
| "Checkpoint failed" | Git state dirty or unavailable | Commit/stash current changes, retry |
| "ledger-next: all-done" | All units already complete | Proceed to resolver |

## Pipeline Position

```
plan-brainstorming → plan-writing → plan-iterative-revision → plan-splitter → [YOU ARE HERE] → plan-resolver
```

**Previous:** `plan-splitter` (produces staged roadmap) or `plan-writing` (for small plans)  
**Next:** `plan-resolver` (audits implementation correctness)
