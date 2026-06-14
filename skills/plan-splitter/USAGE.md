# plan-splitter — Quick Reference

Decompose a large plan into self-contained stages, each executable in a single agent pass.

## How to Invoke

In VS Code Copilot chat, type:

```
/plan-splitter <plan-path> [revision-model] [verify=...] [verify_depth=...] [verify_mode=...]
```

### Usage Examples

```bash
# Minimal — let the skill decide whether to split
/plan-splitter docs/plans/plan01-modernization.md

# With a specific model for subagent verification
/plan-splitter docs/plans/plan01-modernization.md "Claude Opus 4 (copilot)"

# Verify all stages deeply after splitting
/plan-splitter docs/plans/plan01-modernization.md verify=all verify_depth=deep

# Audit-only verification (no fixes to stages)
/plan-splitter .docs/.plans/refactor/plan.md verify=all verify_depth=standard verify_mode=audit-only

# Skip deep verification entirely
/plan-splitter docs/plans/plan01-modernization.md verify=none
```

## Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| Plan file path | **Yes** | — | Path to the master plan `.md` file |
| Revision model | No | Current active model | Model name for subagent verification |
| `verify` | No | `ask` | `ask` / `all` / `none` — deep verification scope |
| `verify_depth` | No | `standard` | `quick` / `standard` / `deep` — depth for plan-iterative-revision |
| `verify_mode` | No | `full-cycle` | `full-cycle` / `audit-only` — fix stages or just review |

## What Happens

```
1. BOOTSTRAP — read plan, detect language, preflight write check
2. GATE DECISION — evaluate 5 factors: split or not?
   → "Don't split" → outputs gate-pass notice, exits (not an error)
   → "Split" → continue
3. ANALYSIS — find stage boundaries, dependency graph, weights (🔴/🟡/🟢)
4. DRAFT & CONFIRM — show split table to user, one retry if rejected
5. GENERATE FILES — write roadmap + stg01..stgN files
6. VERIFY (3 levels) — formal/cross-validation/content check
7. OPTIONAL DEEP VERIFY — run plan-iterative-revision on selected stages
```

## Output Files

All files are created **next to** the original plan (which is NEVER modified):

| File | Purpose |
|---|---|
| `<base>-stg00-roadmap.md` | Stage map: dependencies, parallel groups, weights |
| `<base>-stg01.md` ... `<base>-stgNN.md` | Self-contained stage files |
| `<base>-stg00-verify-baseline.json` | Verification snapshot (if deep verify runs) |
| `<base>-stg00-verify-ledger.json` | Verification results ledger |

## Gate Decision

The skill may decide the plan does NOT need splitting (too small, already focused). This is a valid outcome — you'll get a `gate-pass` notice explaining why.

## Verification Options

When asked about deep verification:
- **all** — verify every stage with `plan-iterative-revision`
- **subset** — verify only selected stages (e.g., `stg01, stg03`)
- **none** — skip deep verification (only formal + cross-validation done)

## Prerequisites

- Python ≥ 3.8 in PATH
- File write tools available
- Original plan will NOT be modified (read-only)

## Checklist Before Invoking

- [ ] Plan exists and is a finalized implementation plan (ideally already passed iterative-revision)
- [ ] Plan is large enough to warrant splitting (>15 tasks is a good heuristic)
- [ ] Directory is writable for stg-file creation

## Common Errors

| Symptom | Cause | Fix |
|---|---|---|
| "Gate: don't split" | Plan is small/focused enough | Not an error — proceed to executor directly |
| "Cannot create stg files" | Write tools unavailable | Enable file write mode |
| Conflict: existing stg files | Previous split exists | Choose: overwrite / rename / abort |
| Stage too large (>15 tasks) | Coarse split | Re-run splitter on that specific stage |

## Pipeline Position

```
plan-brainstorming → plan-writing → plan-iterative-revision → [YOU ARE HERE] → plan-executor → plan-resolver
```

**Previous:** `plan-iterative-revision` (validates the plan)  
**Next:** `plan-executor` (executes stages one by one)
